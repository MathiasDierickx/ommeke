"""Pure tests voor veilige en adresseerbare route-artifacts."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import artifacts, config


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


def test_artifact_descriptor_has_stable_uri_size_and_hash():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        path = artifacts.safe_output_path("abc123", "route.gpx")
        path.write_bytes(b"<gpx/>")

        item = artifacts.describe("abc123", "route.gpx")

        assert item["uri"] == "lusmaker://drafts/abc123/route.gpx"
        assert item["mime_type"] == "application/gpx+xml"
        assert item["bytes"] == 6
        assert len(item["sha256"]) == 64
        assert artifacts.read("abc123", "route.gpx") == b"<gpx/>"


def test_mcp_output_path_stays_inside_its_draft_directory():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        allowed = artifacts.safe_output_path("abc123", "route.gpx", "eigen.gpx")
        assert allowed == Path(temp_dir).resolve() / "exports/abc123/eigen.gpx"

        try:
            artifacts.safe_output_path("abc123", "route.gpx", "../ander.gpx")
        except artifacts.ArtifactError as exc:
            assert "artifactmap" in str(exc)
        else:
            raise AssertionError("pad buiten de draftmap werd aanvaard")


def test_unknown_or_missing_artifact_gives_clear_error():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        try:
            artifacts.read("abc123", "route.gpx")
        except artifacts.ArtifactError as exc:
            assert "bestaat niet" in str(exc)
            assert "routeer eerst" in str(exc)
        else:
            raise AssertionError("ontbrekend artifact werd gelezen")


def test_export_reference_is_injectable_for_http_and_stdio_modes():
    path = "/tmp/lusmaker/exports/abc123/route.gpx"
    assert artifacts.output_reference(
        path, "abc123", "route.gpx", http_mode=False
    ) == path
    assert artifacts.output_reference(
        path,
        "abc123",
        "route.gpx",
        http_mode=True,
        uid="user+123",
        public_url="https://routes.example.test/base/",
    ) == (
        "https://routes.example.test/base/files/"
        "user%2B123/abc123/route.gpx"
    )


def test_http_delivery_changes_file_references_and_descriptors_only_in_scope():
    with tempfile.TemporaryDirectory() as temp_dir, _home(Path(temp_dir)):
        previous_url = os.environ.get("LUSMAKER_PUBLIC_URL")
        os.environ["LUSMAKER_PUBLIC_URL"] = "https://routes.example.test"
        try:
            with config.user_scope("alice"), artifacts.delivery_mode(True):
                path = artifacts.safe_output_path("abc123", "route.gpx")
                path.write_bytes(b"<gpx/>")
                assert artifacts.output_reference(
                    path, "abc123", "route.gpx"
                ) == "https://routes.example.test/files/alice/abc123/route.gpx"
                assert artifacts.describe("abc123", "route.gpx")["uri"] == (
                    "https://routes.example.test/files/alice/abc123/route.gpx"
                )

            assert artifacts.output_reference(
                path, "abc123", "route.gpx"
            ) == str(path)
        finally:
            if previous_url is None:
                os.environ.pop("LUSMAKER_PUBLIC_URL", None)
            else:
                os.environ["LUSMAKER_PUBLIC_URL"] = previous_url
