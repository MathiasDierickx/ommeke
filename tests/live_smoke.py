"""Opt-in regressiesmoke tegen de echte GraphHopper van de default-regio."""
import copy

from lusmaker import draft
from tests.regression_support import (
    SCENARIOS,
    fixture_path,
    format_metrics,
    invariant_failures,
    load_fixture,
    metrics,
)


def main() -> None:
    missing = [fixture_path(name).name for name in SCENARIOS if not fixture_path(name).exists()]
    if missing:
        print(
            "Fixtures ontbreken: "
            + ", ".join(missing)
            + ". Neem ze eerst op met `python -m tests.record_fixtures`."
        )
        raise SystemExit(1)

    rows = []
    failures = []
    for name in SCENARIOS:
        fixture = load_fixture(name)
        scenario_draft = copy.deepcopy(fixture["draft"])
        draft.route(scenario_draft, copy.deepcopy(fixture["climbs"]))
        values = metrics(name, scenario_draft)
        rows.append((name, values))
        failures.extend(
            f"{name}: {failure}"
            for failure in invariant_failures(name, scenario_draft)
        )

    print(format_metrics(rows))
    if failures:
        print()
        for failure in failures:
            print(f"FOUT {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
