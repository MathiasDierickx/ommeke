"""Controleer selectie, isolatie en foutpropagatie van de component-CLI."""
import subprocess
from lusmaker import checks


def test_every_test_module_belongs_to_a_component():
    assigned = {name for names in checks.available().values() for name in names}
    actual = {p.stem.removeprefix('test_') for p in (checks.ROOT / 'tests').glob('test_*.py')}
    assert assigned == actual, actual - assigned


def test_component_failure_is_reported_and_runs_with_isolated_home():
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs['env']['LUSMAKER_HOME'] != str(checks.ROOT)
        assert 'LUSMAKER_STATE_BUCKET' not in kwargs['env']
        return subprocess.CompletedProcess(command, 1, '{"failed": 1}', 'fout')
    result = checks.run('engine', runner=run)
    assert not result['ok']
    assert result['checks'][0]['output']['failed'] == 1
    assert 'regression' in calls[0][0]


def test_component_timeout_fails_without_running_live_checks():
    def run(command, **kwargs):
        assert 'live_smoke' not in ' '.join(command)
        raise subprocess.TimeoutExpired(command, 1)
    assert not checks.run('api', runner=run)['ok']
