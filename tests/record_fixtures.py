"""Neem de T9-cassettes handmatig op tegen de lokale GraphHopper."""
import copy

from lusmaker import draft, gh
from lusmaker.recording import RecordingPost
from tests.regression_support import (
    SCENARIOS,
    format_metrics,
    invariant_failures,
    metrics,
    recording_scenarios,
    write_fixture,
)


def main() -> None:
    scenarios = recording_scenarios()
    rows = []
    failures = []
    for name in SCENARIOS:
        scenario_draft, climb_db = scenarios[name]
        fixture_draft = copy.deepcopy(scenario_draft)
        recorder = RecordingPost(gh._post)

        def recording_route(points, **kwargs):
            # zelfde gepinde capability-set als de replay-tests: cassettes
            # blijven deterministisch, area-regels worden apart unit-getest
            return gh.route(points, area_evs=set(), **kwargs)

        draft.route(
            scenario_draft,
            climb_db,
            router=recording_route,
            post_fn=recorder,
        )
        values = metrics(name, scenario_draft)
        rows.append((name, values))
        scenario_failures = invariant_failures(name, scenario_draft)
        if scenario_failures:
            failures.extend(f"{name}: {failure}" for failure in scenario_failures)
            continue
        path = write_fixture(
            name,
            {
                "draft": fixture_draft,
                "climbs": climb_db,
                "responses": recorder.responses,
            },
        )
        print(f"opgenomen: {path}")

    print()
    print(format_metrics(rows))
    if failures:
        print()
        for failure in failures:
            print(f"FOUT {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
