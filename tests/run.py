"""Kleine pytest-stijl testrunner zonder externe testdependency."""
import importlib
import pkgutil
import traceback

import tests


def main() -> None:
    failures = 0
    tests_run = 0
    for module_info in sorted(pkgutil.iter_modules(tests.__path__), key=lambda item: item.name):
        if not module_info.name.startswith("test_"):
            continue
        module = importlib.import_module(f"tests.{module_info.name}")
        for name in sorted(dir(module)):
            test = getattr(module, name)
            if not name.startswith("test_") or not callable(test):
                continue
            tests_run += 1
            try:
                test()
                print(f"PASS {module_info.name}.{name}")
            except Exception:
                failures += 1
                print(f"FAIL {module_info.name}.{name}")
                traceback.print_exc()
    print(f"{tests_run} tests, {failures} mislukt")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
