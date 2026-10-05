"""Offline controle: alle uitgaande verzoeken dragen de User-Agent met contact."""

import re
import urllib.request
from pathlib import Path
from unittest import mock

from lusmaker import config, heat, route_sources


class _Response:
    headers = {"Content-Length": "0"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return b""


def test_user_agent_bevat_contact():
    assert "contact:" in config.USER_AGENT and "@" in config.USER_AGENT


def test_alle_user_agents_gebruiken_de_gedeelde_constante():
    root = Path(config.__file__).parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for match in re.finditer(r'"User-Agent":\s*([^,}\n)]+)', line):
                if match.group(1).strip() not in {"config.USER_AGENT", "USER_AGENT"}:
                    offenders.append(f"{path.name}:{number}")
    assert not offenders, f"User-Agent zonder gedeelde constante: {offenders}"


def test_http_clients_sturen_user_agent_met_contact():
    seen = []

    def fake(request, *args, **kwargs):
        seen.append(request.get_header("User-agent"))
        return _Response()

    with mock.patch.object(urllib.request, "urlopen", fake):
        heat._fetch_url("https://example.invalid/a")
        route_sources.fetch_url("https://example.invalid/b")
    assert len(seen) == 2
    assert all(value == config.USER_AGENT and "contact:" in value for value in seen)
