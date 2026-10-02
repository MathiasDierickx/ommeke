from lusmaker import pilot


def test_feedback_requires_owned_route_and_preserves_revision():
    saved = []
    result = pilot.feedback('abc', 'wens_gemist', 'Geen kasseien gevraagd',
        load=lambda value: {'id': value, 'revision': 7}, put=lambda *a, **kw: saved.append(a))
    assert result['status'] == 'received'
    assert saved[0][1]['revision'] == 7
    assert saved[0][1]['category'] == 'wens_gemist'
    for category, comment in [('fout', ''), ('anders', 'x'*1001)]:
        try:
            pilot.feedback('abc', category, comment, load=lambda value: {}, put=lambda *a, **k: None)
        except ValueError:
            pass
        else:
            raise AssertionError('ongeldige feedback aanvaard')
