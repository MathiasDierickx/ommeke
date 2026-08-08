"""Pure tests voor request-lokale gebruikersopslag."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import artifacts, config, draft, profiles


@contextmanager
def _home(path: Path):
    previous = os.environ.get("LUSMAKER_HOME")
    os.environ["LUSMAKER_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous


def test_user_scope_resolves_only_personal_paths_and_restores_local_fallback():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        home = Path(temp_dir)
        assert config.current_user_id() == "local"
        assert config.DRAFTS == home / "drafts"
        assert config.profiles_path() == home / "profiles"
        assert artifacts.root() == home / "exports"
        shared_cache = config.CACHE

        with config.user_scope("oauth-user_123"):
            personal = home / "users" / "oauth-user_123"
            assert config.DRAFTS == personal / "drafts"
            assert config.profiles_path() == personal / "profiles"
            assert artifacts.root() == personal / "exports"
            assert config.CACHE == shared_cache

        assert config.current_user_id() == "local"
        assert config.DRAFTS == home / "drafts"


def test_user_scope_isolates_drafts_profiles_and_exports():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        with config.user_scope("alice"):
            alice = draft.new(
                start={"lat": 50.8, "lon": 3.7, "label": "Start"},
                name="Alice",
                loop=True,
                end=None,
            )
            profiles.save(profiles.default_document("persoonlijk"))
            artifacts.safe_output_path(alice["id"], "route.gpx").write_bytes(
                b"alice"
            )

        with config.user_scope("bob"):
            assert draft.list_all() == []
            assert profiles.list_all() == []
            try:
                draft.load(alice["id"])
            except draft.DraftError as exc:
                assert "bestaat niet" in str(exc)
            else:
                raise AssertionError("draft van andere gebruiker werd gelezen")
            try:
                artifacts.read(alice["id"], "route.gpx")
            except artifacts.ArtifactError as exc:
                assert "bestaat niet" in str(exc)
            else:
                raise AssertionError("export van andere gebruiker werd gelezen")


def test_user_and_draft_path_traversal_are_rejected():
    for uid in ("", ".", "..", "../alice", "alice/bob", "alice\\bob", "x\n"):
        try:
            with config.user_scope(uid):
                pass
        except ValueError as exc:
            assert "user-id" in str(exc)
        else:
            raise AssertionError(f"ongeldige user-id werd aanvaard: {uid!r}")

    for draft_id in ("../alice", "alice/bob", "x.json", ""):
        try:
            draft.load(draft_id)
        except draft.DraftError as exc:
            assert "ongeldig draft-id" in str(exc)
        else:
            raise AssertionError(f"ongeldig draft-id werd aanvaard: {draft_id!r}")
