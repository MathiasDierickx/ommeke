"""Packversies, features en hosted-datastroom: offline."""
import contextlib
import io
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from deploy.aws.prepare_region import prepare
from lusmaker import cli, config, pack_manifest, provision
from tests.test_provision import _isolated_home


def _region_with_cache(home):
    region = config.register_region('zeeland', 'europe/netherlands/zeeland', (51.2, 3.4, 51.8, 4.3), 8989, home=home)
    region.cache.mkdir(parents=True)
    region.data.mkdir(parents=True)
    (region.data / region.pbf_name).write_bytes(b'pbf')
    (region.gh_dir / 'custom_models').mkdir(parents=True)
    (region.gh_dir / 'config.yml').write_text('graphhopper:\n  graph.encoded_values: country\n')
    return region


def test_manifest_records_source_date_and_profile_versions_and_validates():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            region = _region_with_cache(home)
            os.utime(region.data / region.pbf_name, (1_760_000_000, 1_760_000_000))
            manifest = pack_manifest.metadata(region)
    assert manifest['source_data_date'] == datetime.fromtimestamp(1_760_000_000, UTC).date().isoformat()
    assert manifest['source_data_basis'] == 'pbf'
    assert manifest['profile_config_version'] == pack_manifest.PROFILE_CONFIG_VERSION
    assert len(manifest['gh_config_sha256']) == 64 and manifest['routing_profile']
    checked = pack_manifest.validate(manifest)
    assert checked['source_data_date'] == manifest['source_data_date']
    summary = pack_manifest.describe(manifest)
    assert summary['brondata_datum'] == manifest['source_data_date']
    assert summary['features']['persoonlijke_heat'] is False
    assert set(summary['features']) == {'waterlopen', 'landmarks', 'gebieden', 'persoonlijke_heat'}


def test_old_manifests_still_validate_and_new_profile_mismatch_is_rejected():
    old = {'pack_format_version': 2, 'features': {'landmarks': True}, 'built_at': '2026-01-01T00:00:00+00:00'}
    assert pack_manifest.validate(old)['profile_config_version'] is None
    assert pack_manifest.describe(old)['brondata_datum'] is None
    try:
        pack_manifest.validate({**old, 'profile_config_version': pack_manifest.PROFILE_CONFIG_VERSION + 1})
    except ValueError as exc:
        assert 'opnieuw bouwen' in str(exc)
    else:
        raise AssertionError('andere profielconfiguratie aanvaard')


def test_region_info_cli_reads_pack_and_local_region_in_dutch_json():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            _region_with_cache(home)
            output = home / 'pack.tar.gz'
            provision.create_pack('zeeland', output, home=home)
            for argv in (['region', 'info', '--pack', str(output)], ['region', 'info', 'zeeland']):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    try:
                        cli.main(argv)
                    except SystemExit:
                        pass
                result = json.loads(buffer.getvalue())
                assert result['slug'] == 'zeeland' and result['brondata_datum']
                assert result['features']['persoonlijke_heat'] is False
                assert 'profielconfig_versie' in result


def test_health_exposes_installed_region_pack_summary():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            region = _region_with_cache(home)
            assert pack_manifest.installed_summary(region) is None
            (region.root / 'pack.json').write_text(json.dumps({**pack_manifest.metadata(region), 'slug': 'zeeland'}))
            summary = pack_manifest.installed_summary(region)
    assert summary['slug'] == 'zeeland' and summary['brondata_datum']


def test_prepare_region_rejects_pack_with_personal_heat():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        pack = root / 'pack.tar.gz'
        payload = root / 'pack.json'
        payload.write_text(json.dumps({'slug': 'zeeland', 'contains_personal_heat': True,
                                       'gh_image': config.GRAPH_HOPPER_IMAGE}))
        with tarfile.open(pack, 'w:gz') as archive:
            archive.add(payload, arcname='pack.json')
        try:
            prepare(pack, 'zeeland', root / 'context')
        except RuntimeError as exc:
            assert 'persoonlijke heat' in str(exc)
        else:
            raise AssertionError('pack met persoonlijke heat is aanvaard')
        assert not (root / 'context' / 'regions.json').exists()
