"""Opt-in end-to-endtest tegen de gedeployde Lusmaker-productieketen."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


PROMPT = "maak een lus van 30 km vanuit Wetteren"
DEFAULT_REGION = "eu-west-1"
_NO_BODY = object()


class CheckError(RuntimeError):
    """Een productiestap voldeed niet aan het verwachte contract."""


@dataclass(frozen=True)
class E2EConfig:
    api: str
    pool_id: str = ""
    client_id: str = ""
    username: str = ""
    password: str = ""
    region: str = DEFAULT_REGION

    @classmethod
    def from_env(
        cls,
        *,
        api: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "E2EConfig":
        values = os.environ if environ is None else environ
        return cls(
            api=(api or values.get("LUSMAKER_E2E_API", "")).rstrip("/"),
            pool_id=values.get("LUSMAKER_E2E_POOL_ID", ""),
            client_id=values.get("LUSMAKER_E2E_CLIENT_ID", ""),
            username=values.get("LUSMAKER_E2E_USERNAME", ""),
            password=values.get("LUSMAKER_E2E_PASSWORD", ""),
            region=values.get("LUSMAKER_E2E_REGION", DEFAULT_REGION),
        )


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] | None = None

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckError("response bevat geen geldige JSON") from exc

    def header(self, name: str) -> str | None:
        wanted = name.casefold()
        for key, value in (self.headers or {}).items():
            if key.casefold() == wanted:
                return value
        return None


@dataclass(frozen=True)
class StepResult:
    number: int
    name: str
    status: str
    duration_s: float
    detail: str = ""


@dataclass(frozen=True)
class RunReport:
    steps: tuple[StepResult, ...]

    @property
    def exit_code(self) -> int:
        return 1 if any(step.status == "FOUT" for step in self.steps) else 0


RequestFn = Callable[..., HTTPResponse]
AuthFn = Callable[[E2EConfig], str]


class UrllibClient:
    """Kleine urllib-client die HTTP-foutstatussen als responses teruggeeft."""

    def __init__(
        self,
        base_url: str,
        *,
        verbose: bool = False,
        printer: Callable[[str], None] = print,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("--api moet een absolute http(s)-URL zijn")
        self.base_url = base_url.rstrip("/")
        self.origin = (parsed.scheme.casefold(), parsed.netloc.casefold())
        self.verbose = verbose
        self.printer = printer

    def _url(self, target: str) -> str:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            origin = (parsed.scheme.casefold(), parsed.netloc.casefold())
            if origin != self.origin:
                raise CheckError(
                    "server verwees naar een bestand buiten de API-origin"
                )
            return target
        return f"{self.base_url}/{target.lstrip('/')}"

    def __call__(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = _NO_BODY,
        timeout: float = 30,
    ) -> HTTPResponse:
        url = self._url(target)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "lusmaker-e2e/1",
            **(headers or {}),
        }
        data = None
        if json_body is not _NO_BODY:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=data, headers=request_headers, method=method)
        if self.verbose:
            self.printer(f"    HTTP {method} {url}")
        try:
            with urlopen(request, timeout=timeout) as response:
                result = HTTPResponse(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            result = HTTPResponse(
                status=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (URLError, OSError) as exc:
            raise CheckError(f"HTTP-request mislukt: {exc}") from exc
        if self.verbose:
            self.printer(
                f"    HTTP {result.status} ({len(result.body)} bytes ontvangen)"
            )
        return result


def _required_auth_values(config: E2EConfig) -> None:
    missing = [
        env_name
        for env_name, value in (
            ("LUSMAKER_E2E_POOL_ID", config.pool_id),
            ("LUSMAKER_E2E_CLIENT_ID", config.client_id),
            ("LUSMAKER_E2E_USERNAME", config.username),
            ("LUSMAKER_E2E_PASSWORD", config.password),
        )
        if not value
    ]
    if missing:
        raise CheckError("Cognito-config ontbreekt: " + ", ".join(missing))


def cognito_login(config: E2EConfig) -> str:
    """Log via Cognito SRP in en geef de access token terug."""
    _required_auth_values(config)
    try:
        from pycognito import Cognito
    except ImportError as exc:
        raise CheckError(
            "pycognito ontbreekt; installeer met "
            "`.venv/bin/python -m pip install -e '.[e2e]'`"
        ) from exc

    kwargs: dict[str, Any] = {"username": config.username}
    parameters = inspect.signature(Cognito).parameters
    if "pool_region" in parameters:
        kwargs["pool_region"] = config.region
    elif "user_pool_region" in parameters:
        kwargs["user_pool_region"] = config.region
    elif "boto3_client_kwargs" in parameters:
        kwargs["boto3_client_kwargs"] = {"region_name": config.region}

    user = Cognito(config.pool_id, config.client_id, **kwargs)
    auth_result = user.authenticate(password=config.password)
    token = getattr(user, "access_token", None)
    if not token and isinstance(auth_result, dict):
        token = auth_result.get("AccessToken")
        if not token and isinstance(auth_result.get("AuthenticationResult"), dict):
            token = auth_result["AuthenticationResult"].get("AccessToken")
    if not isinstance(token, str) or not token:
        raise CheckError("Cognito-login leverde geen access token op")
    return token


def _json_object(response: HTTPResponse) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise CheckError("response moet een JSON-object zijn")
    return payload


def _response_detail(response: HTTPResponse) -> str:
    try:
        payload = response.json()
    except CheckError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("error_description")
        code = payload.get("code")
        if error and code:
            return f"{code}: {error}"
        if error:
            return str(error)
    text = response.body.decode("utf-8", errors="replace").strip()
    return text[:240] or "lege response"


def _expect_status(response: HTTPResponse, *expected: int) -> None:
    if response.status not in expected:
        wanted = "/".join(str(value) for value in expected)
        raise CheckError(
            f"verwacht HTTP {wanted}, kreeg {response.status}: "
            f"{_response_detail(response)}"
        )


def _absolute_http_url(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise CheckError(f"OAuth-metadata mist geldige `{field}`")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CheckError(f"OAuth-metadata bevat ongeldige `{field}`")


def validate_oauth_metadata(payload: Any) -> None:
    """Valideer de velden en URI-vormen uit RFC 9728 die aanwezig zijn."""
    if not isinstance(payload, dict):
        raise CheckError("OAuth-metadata moet een JSON-object zijn")
    _absolute_http_url(payload.get("resource"), "resource")
    authorization_servers = payload.get("authorization_servers")
    if authorization_servers is not None:
        if (
            not isinstance(authorization_servers, list)
            or not authorization_servers
        ):
            raise CheckError("`authorization_servers` moet een niet-lege lijst zijn")
        for value in authorization_servers:
            _absolute_http_url(value, "authorization_servers")
    for field in (
        "scopes_supported",
        "bearer_methods_supported",
        "resource_signing_alg_values_supported",
    ):
        values = payload.get(field)
        if values is not None and (
            not isinstance(values, list)
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise CheckError(f"OAuth-metadata bevat ongeldige `{field}`")


def validate_gpx(payload: bytes) -> None:
    if not payload:
        raise CheckError("GPX-bestand is leeg")
    if not payload.startswith(b"<?xml"):
        raise CheckError("GPX-bestand begint niet met `<?xml`")


def _mcp_payload(response: HTTPResponse) -> dict[str, Any]:
    """Lees zowel JSON-responses als Streamable-HTTP SSE-responses."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except CheckError:
        pass
    for line in response.body.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line.removeprefix("data:").strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise CheckError("MCP-response bevat geen geldig JSON-RPC-bericht")


def _mcp_result(response: HTTPResponse) -> dict[str, Any]:
    _expect_status(response, 200)
    payload = _mcp_payload(response)
    if payload.get("error"):
        raise CheckError(f"MCP-fout: {payload['error']}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise CheckError("MCP-response mist een result-object")
    return result


class E2ERunner:
    def __init__(
        self,
        config: E2EConfig,
        *,
        request: RequestFn,
        authenticate: AuthFn = cognito_login,
        printer: Callable[[str], None] = print,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.config = config
        self.request = request
        self.authenticate = authenticate
        self.printer = printer
        self.clock = clock
        self.steps: list[StepResult] = []

    def _record(
        self,
        number: int,
        name: str,
        status: str,
        started: float,
        detail: str = "",
    ) -> None:
        result = StepResult(
            number,
            name,
            status,
            max(0.0, self.clock() - started),
            detail,
        )
        self.steps.append(result)
        suffix = f" — {detail}" if detail else ""
        self.printer(
            f"{number}. {name}: {status} ({result.duration_s:.2f} s){suffix}"
        )

    def _attempt(
        self,
        number: int,
        name: str,
        action: Callable[[], tuple[Any, str]],
    ) -> Any:
        started = self.clock()
        try:
            value, detail = action()
        except Exception as exc:
            self._record(number, name, "FOUT", started, str(exc))
            return None
        self._record(number, name, "OK", started, detail)
        return value

    def _skip(self, number: int, name: str, reason: str) -> None:
        started = self.clock()
        self._record(number, name, "SKIP", started, reason)

    def _health(self) -> tuple[None, str]:
        response = self.request("GET", "/health", timeout=120)
        _expect_status(response, 200)
        if _json_object(response).get("status") != "ok":
            raise CheckError("health-response heeft geen status `ok`")
        return None, "status=ok"

    def _anonymous_mcp(self) -> tuple[None, str]:
        response = self.request("POST", "/mcp", timeout=120)
        _expect_status(response, 401)
        return None, "HTTP 401 zoals verwacht"

    def _metadata(self) -> tuple[None, str]:
        response = self.request(
            "GET", "/.well-known/oauth-protected-resource", timeout=120
        )
        _expect_status(response, 200)
        validate_oauth_metadata(response.json())
        return None, "RFC 9728-metadata geldig"

    def _login(self) -> tuple[str, str]:
        token = self.authenticate(self.config)
        if not isinstance(token, str) or not token:
            raise CheckError("Cognito-login leverde geen access token op")
        return token, "access token ontvangen"

    @staticmethod
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _list_conversations(self, token: str) -> tuple[None, str]:
        response = self.request(
            "GET",
            "/api/conversations",
            headers=self._auth_headers(token),
            timeout=120,
        )
        _expect_status(response, 200)
        conversations = _json_object(response).get("conversations")
        if not isinstance(conversations, list):
            raise CheckError("response mist de gesprekkenlijst")
        return None, f"{len(conversations)} gesprek(ken)"

    def _create_conversation(self, token: str) -> tuple[str, str]:
        response = self.request(
            "POST",
            "/api/conversations",
            headers=self._auth_headers(token),
            json_body={},
            timeout=120,
        )
        _expect_status(response, 201)
        conversation = _json_object(response).get("conversation")
        conversation_id = (
            conversation.get("id") if isinstance(conversation, dict) else None
        )
        if not isinstance(conversation_id, str) or not conversation_id:
            raise CheckError("response mist een conversation-id")
        return conversation_id, f"conversation={conversation_id}"

    def _send_message(
        self, token: str, conversation_id: str
    ) -> tuple[list[str], str]:
        path = f"/api/conversations/{quote(conversation_id, safe='')}/messages"
        response = self.request(
            "POST",
            path,
            headers=self._auth_headers(token),
            json_body={"content": PROMPT},
            timeout=600,
        )
        try:
            payload = _json_object(response)
        except CheckError:
            payload = {}
        if response.status == 502 or payload.get("code") == "model_unavailable":
            raise CheckError(
                "Bedrock-modeltoegang: check use-case-formulier/betaalmethode"
            )
        _expect_status(response, 200, 201)
        if not payload.get("message"):
            raise CheckError("berichtresponse mist `message`")
        route_ids = payload.get("route_ids")
        if not isinstance(route_ids, list):
            raise CheckError("berichtresponse mist `route_ids`")
        if not route_ids or not all(
            isinstance(route_id, str) and route_id for route_id in route_ids
        ):
            raise CheckError("berichtresponse bevat geen bruikbaar route-id")
        return route_ids, f"{len(route_ids)} route-id(s)"

    def _route_files(self, token: str, route_id: str) -> tuple[None, str]:
        response = self.request(
            "GET",
            f"/api/routes/{quote(route_id, safe='')}",
            headers=self._auth_headers(token),
            timeout=120,
        )
        _expect_status(response, 200)
        route = _json_object(response).get("route")
        if not isinstance(route, dict):
            raise CheckError("routeresponse mist `route`")
        gpx_ref = route.get("download_url") or route.get("gpx_url")
        preview_ref = route.get("preview_url")
        if not isinstance(gpx_ref, str) or not gpx_ref:
            raise CheckError("route mist een GPX-referentie")
        if not isinstance(preview_ref, str) or not preview_ref:
            raise CheckError("route mist een preview-referentie")

        gpx_response = self.request(
            "GET", gpx_ref, headers=self._auth_headers(token), timeout=120
        )
        _expect_status(gpx_response, 200)
        validate_gpx(gpx_response.body)
        preview_response = self.request(
            "GET", preview_ref, headers=self._auth_headers(token), timeout=120
        )
        _expect_status(preview_response, 200)
        if not preview_response.body:
            raise CheckError("previewbestand is leeg")
        return (
            None,
            f"GPX {len(gpx_response.body)} B, "
            f"preview {len(preview_response.body)} B",
        )

    def _mcp(self, token: str) -> tuple[None, str]:
        headers = {
            **self._auth_headers(token),
            "Accept": "application/json, text/event-stream",
        }
        initialize = self.request(
            "POST",
            "/mcp",
            headers=headers,
            json_body={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "lusmaker-e2e", "version": "1"},
                },
            },
            timeout=120,
        )
        initialize_result = _mcp_result(initialize)
        protocol_version = initialize_result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise CheckError("MCP initialize mist protocolVersion")

        session_id = initialize.header("mcp-session-id")
        request_headers = {**headers, "MCP-Protocol-Version": protocol_version}
        if session_id:
            request_headers["Mcp-Session-Id"] = session_id
            initialized = self.request(
                "POST",
                "/mcp",
                headers=request_headers,
                json_body={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                timeout=120,
            )
            _expect_status(initialized, 200, 202, 204)

        listed = self.request(
            "POST",
            "/mcp",
            headers=request_headers,
            json_body={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
            timeout=120,
        )
        tools = _mcp_result(listed).get("tools")
        if not isinstance(tools, list):
            raise CheckError("MCP tools/list mist een toollijst")
        names = {
            tool.get("name")
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        if "plan_route" not in names:
            raise CheckError("MCP lite-toolset mist `plan_route`")
        mode = "sessieheader hergebruikt" if session_id else "stateless"
        return None, f"plan_route aanwezig ({len(names)} tools; {mode})"

    def run(self) -> RunReport:
        self.steps = []
        self._attempt(1, "Health", self._health)
        self._attempt(2, "MCP zonder token", self._anonymous_mcp)
        self._attempt(3, "OAuth-metadata", self._metadata)
        token = self._attempt(4, "Cognito-login", self._login)

        if token:
            self._attempt(
                5,
                "Gesprekken ophalen",
                lambda: self._list_conversations(token),
            )
            conversation_id = self._attempt(
                6,
                "Gesprek maken",
                lambda: self._create_conversation(token),
            )
        else:
            self._skip(5, "Gesprekken ophalen", "Cognito-login faalde")
            self._skip(6, "Gesprek maken", "Cognito-login faalde")
            conversation_id = None

        if token and conversation_id:
            route_ids = self._attempt(
                7,
                "Routebericht versturen",
                lambda: self._send_message(token, conversation_id),
            )
        else:
            self._skip(7, "Routebericht versturen", "geen gesprek beschikbaar")
            route_ids = None

        if token and route_ids:
            self._attempt(
                8,
                "Routebestanden ophalen",
                lambda: self._route_files(token, route_ids[-1]),
            )
        else:
            self._skip(8, "Routebestanden ophalen", "geen route-id beschikbaar")

        if token:
            self._attempt(9, "MCP-toolset", lambda: self._mcp(token))
        else:
            self._skip(9, "MCP-toolset", "Cognito-login faalde")

        report = RunReport(tuple(self.steps))
        self._print_report(report)
        return report

    def _print_report(self, report: RunReport) -> None:
        self.printer("")
        self.printer("Eindrapport")
        name_width = max(len("Stap"), *(len(step.name) for step in report.steps))
        self.printer(f"{'#':>2}  {'Stap':<{name_width}}  Status  Duur")
        for step in report.steps:
            self.printer(
                f"{step.number:>2}  {step.name:<{name_width}}  "
                f"{step.status:<6}  {step.duration_s:.2f} s"
            )
        outcome = "OK" if report.exit_code == 0 else "FOUT"
        self.printer(f"Resultaat: {outcome}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.e2e_prod",
        description="Test de volledige gedeployde Lusmaker-keten zonder UI.",
    )
    parser.add_argument(
        "--api",
        help="Function-URL; standaard LUSMAKER_E2E_API",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="toon elke HTTP-request en responsstatus",
    )
    args = parser.parse_args(argv)
    config = E2EConfig.from_env(api=args.api)
    if not config.api:
        print("FOUT configuratie: --api of LUSMAKER_E2E_API is verplicht")
        return 1
    try:
        client = UrllibClient(config.api, verbose=args.verbose)
    except ValueError as exc:
        print(f"FOUT configuratie: {exc}")
        return 1
    report = E2ERunner(config, request=client).run()
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
