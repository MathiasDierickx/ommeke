from lusmaker import pack_manifest, heat
from tests.test_aws_state import _aws_bucket


def test_pack_version_validation_accepts_legacy_but_rejects_incompatible_data():
    assert pack_manifest.validate({'slug': 'vlaanderen'})['legacy']
    for manifest in ({'pack_format_version': 99}, {'extract_format_version': -1}, {'gh_image': 'wrong:version'}):
        try:
            pack_manifest.validate(manifest)
        except ValueError:
            pass
        else:
            raise AssertionError('incompatibel pack aanvaard')


def test_hosted_personal_tracks_cannot_write_shared_heat():
    with _aws_bucket():
        for operation in (lambda: heat.seed('/not/read', 'cycling'), heat.build):
            try:
                operation()
            except ValueError as exc:
                assert 'lokale beheerder' in str(exc)
            else:
                raise AssertionError('gedeelde heat gewijzigd vanuit hosted context')
