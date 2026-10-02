"""Offline pytest-stijl runner met modulekeuze en optionele JSON-rapportage."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import importlib
import io
import json
import pkgutil
import sys
import time
import traceback
from unittest import SkipTest

import tests


def _deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}:
        raise RuntimeError("netwerk is uitgeschakeld in de offline testsuite; injecteer de afhankelijkheid")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Offline tests; optioneel specifieke testmodules.")
    parser.add_argument("modules", nargs="*")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    modules = sorted(m.name for m in pkgutil.iter_modules(tests.__path__) if m.name.startswith("test_"))
    selected = {m if m.startswith("test_") else f"test_{m}" for m in args.modules}
    unknown = selected - set(modules)
    if unknown:
        print(json.dumps({"error": f"onbekende testmodules: {', '.join(sorted(unknown))}"}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    sys.addaudithook(_deny_network)
    results = []
    for name in modules:
        if selected and name not in selected:
            continue
        captured = io.StringIO()
        try:
            with redirect_stdout(captured), redirect_stderr(captured):
                module = importlib.import_module(f"tests.{name}")
        except Exception:
            results.append({"name": name, "status": "FAIL", "traceback": traceback.format_exc()})
            continue
        for test_name in sorted(dir(module)):
            test = getattr(module, test_name)
            if not test_name.startswith("test_") or not callable(test):
                continue
            row = {"name": f"{name}.{test_name}", "status": "PASS"}
            started = time.monotonic()
            output = io.StringIO()
            try:
                with redirect_stdout(output), redirect_stderr(output):
                    test()
            except SkipTest as exc:
                row.update(status="SKIP", reason=str(exc))
            except Exception:
                row.update(status="FAIL", traceback=traceback.format_exc())
            row["seconds"] = round(time.monotonic() - started, 4)
            if output.getvalue():
                row["output"] = output.getvalue()
            results.append(row)
    failures = sum(r["status"] == "FAIL" for r in results)
    skipped = sum(r["status"] == "SKIP" for r in results)
    summary = {"tests": len(results), "failed": failures, "skipped": skipped, "results": results}
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for row in results:
            print(f"{row['status']} {row['name']}")
            if row.get("traceback"):
                print(row["traceback"], file=sys.stderr)
            if row.get("reason"):
                print(row["reason"])
        print(f"{len(results)} tests, {failures} mislukt, {skipped} overgeslagen")
    if failures or not results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
