"""Herhaalbare praktijkvragen: echte GH-cassettes plus gecontroleerde randgevallen."""
import json
import sys
from .run import _deny_network
from .test_regression import _replay
from .regression_support import SCENARIOS, metrics
from . import test_acceptance, test_quality
from lusmaker.quality import evaluate


def main():
    sys.addaudithook(_deny_network)
    results = []
    for name in SCENARIOS:
        try:
            route = _replay(name)
            geometry = evaluate(route, {})
            results.append({'scenario': name, 'source': 'opgenomen echte GraphHopper-antwoorden',
                            'ok': geometry['ok'], 'metrics': {**metrics(name, route), **geometry['metrics']}, 'failures': geometry['failures']})
        except Exception as exc:
            results.append({'scenario':name, 'ok':False, 'error':str(exc)})
    for module in (test_acceptance, test_quality):
        for name in sorted(n for n in dir(module) if n.startswith('test_')):
            try:
                getattr(module, name)()
                results.append({'scenario':name.removeprefix('test_'), 'source':'gecontroleerde offline geometrie/routerantwoorden', 'ok':True})
            except Exception as exc:
                results.append({'scenario':name.removeprefix('test_'), 'ok':False, 'error':str(exc)})
    ok = all(result['ok'] for result in results)
    print(json.dumps({'ok':ok, 'scenarios':results},ensure_ascii=False,indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
