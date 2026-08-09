"""Pure S3-adaptertests zonder boto3 of netwerk."""

import hashlib
import io
import os
import tempfile
from contextlib import contextmanager

from pathlib import Path

from lusmaker import artifacts, aws_state, draft, profiles, tenant


class _ClientError(RuntimeError):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class _FakeS3:
    def __init__(self):
        self.objects = {}
        self.etags = {}
        self.counter = 0
        self.presigned = None

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        current = self.etags.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _ClientError("PreconditionFailed")
        if kwargs.get("IfMatch") is not None and kwargs["IfMatch"] != current:
            raise _ClientError("PreconditionFailed")
        payload = kwargs["Body"]
        self.counter += 1
        etag = f'"etag-{len(payload)}-{self.counter}"'
        self.objects[key] = {
            "Body": payload,
            "ContentType": kwargs["ContentType"],
            "Metadata": kwargs["Metadata"],
        }
        self.etags[key] = etag
        return {"ETag": etag}

    def get_object(self, **kwargs):
        key = kwargs["Key"]
        if key not in self.objects:
            raise _ClientError("NoSuchKey")
        item = self.objects[key]
        return {
            **item,
            "Body": io.BytesIO(item["Body"]),
            "ETag": self.etags[key],
        }

    def list_objects_v2(self, **kwargs):
        keys = sorted(key for key in self.objects if key.startswith(kwargs["Prefix"]))
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}

    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)
        self.etags.pop(kwargs["Key"], None)
        return {}

    def delete_objects(self, **kwargs):
        for item in kwargs["Delete"]["Objects"]:
            self.delete_object(Key=item["Key"])
        return {}

    def generate_presigned_url(self, operation, **kwargs):
        self.presigned = (operation, kwargs)
        return "https://state-test.s3.example/download?signature=test"


@contextmanager
def _aws_bucket():
    previous = os.environ.get("LUSMAKER_STATE_BUCKET")
    os.environ["LUSMAKER_STATE_BUCKET"] = "state-test"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_STATE_BUCKET", None)
        else:
            os.environ["LUSMAKER_STATE_BUCKET"] = previous


def test_s3_json_state_is_tenant_scoped_and_conditional():
    client = _FakeS3()
    with _aws_bucket(), tenant.use("user/one"):
        aws_state.put_json("drafts/a.json", {"id": "a"}, create_only=True, client=client)
        loaded, etag = aws_state.get_json("drafts/a.json", client=client)
        assert loaded == {"id": "a"}
        digest = hashlib.sha256(b"user/one").hexdigest()[:20]
        assert list(client.objects) == [
            f"tenants/user-one-{digest}/drafts/a.json"
        ]

        aws_state.put_json(
            "drafts/a.json", {"id": "a", "revision": 2}, etag=etag, client=client
        )
        try:
            aws_state.put_json(
                "drafts/a.json", {"id": "stale"}, etag=etag, client=client
            )
        except aws_state.StateConflict:
            pass
        else:
            raise AssertionError("stale conditional write werd aanvaard")

        assert aws_state.list_json("drafts", client=client)[0]["revision"] == 2


def test_unsafe_and_already_safe_tenant_ids_cannot_collide():
    client = _FakeS3()
    with _aws_bucket(), tenant.use("auth0|user-one"):
        aws_state.put_json("drafts/a.json", {"id": "unsafe"}, client=client)
    with _aws_bucket(), tenant.use("auth0-user-one"):
        aws_state.put_json("drafts/a.json", {"id": "safe"}, client=client)

    assert len(client.objects) == 2
    assert len({key.split("/")[1] for key in client.objects}) == 2


def test_artifact_metadata_contains_hash_and_size():
    client = _FakeS3()
    with _aws_bucket(), tenant.use("abc"):
        result = aws_state.publish_artifact(
            "draft1", "route.gpx", b"<gpx/>", "application/gpx+xml", client=client
        )
        payload, _etag, metadata = aws_state.get_bytes(
            "artifacts/draft1/route.gpx", client=client
        )

    assert payload == b"<gpx/>"
    assert result["bytes"] == 6
    assert metadata["sha256"] == result["sha256"]


def test_artifact_presigned_url_is_tenant_scoped_and_short_lived():
    client = _FakeS3()
    with _aws_bucket(), tenant.use("abc"), aws_state.use_client(client):
        aws_state.publish_artifact(
            "draft1", "route.gpx", b"<gpx/>", "application/gpx+xml"
        )
        url = artifacts.temporary_download_url(
            "draft1", "route.gpx", download_name="Heuvelrit.gpx"
        )

    assert url.startswith("https://state-test.s3.example/download")
    operation, kwargs = client.presigned
    assert operation == "get_object"
    assert kwargs["ExpiresIn"] == 900
    assert kwargs["Params"] == {
        "Bucket": "state-test",
        "Key": "tenants/abc/artifacts/draft1/route.gpx",
        "ResponseContentType": "application/gpx+xml",
        "ResponseContentDisposition": 'attachment; filename="Heuvelrit.gpx"',
    }


def test_tenant_delete_removes_only_the_requested_object_and_prefix():
    client = _FakeS3()
    with _aws_bucket(), tenant.use("abc"):
        aws_state.put_json("drafts/a.json", {"id": "a"}, client=client)
        aws_state.put_json("drafts/b.json", {"id": "b"}, client=client)
        aws_state.put_bytes("artifacts/a/route.gpx", b"gpx", client=client)
        aws_state.put_bytes("artifacts/a/preview.html", b"html", client=client)
        aws_state.delete("drafts/a.json", client=client)
        deleted = aws_state.delete_prefix("artifacts/a", client=client)

    assert deleted == 2
    assert list(client.objects) == ["tenants/abc/drafts/b.json"]


def test_domain_storage_uses_s3_for_drafts_profiles_and_artifacts():
    client = _FakeS3()
    previous_tmp = os.environ.get("LUSMAKER_TMP")
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["LUSMAKER_TMP"] = temp_dir
        try:
            with _aws_bucket(), tenant.use("hosted-user"), aws_state.use_client(client):
                d = draft.new(
                    start={"lat": 50.0, "lon": 4.0, "label": "Start"},
                    name="hosted",
                    loop=True,
                    end=None,
                )
                saved_profile = profiles.save(profiles.default_document("cloud"))
                artifact_path = artifacts.safe_output_path(d["id"], "route.gpx")
                artifact_path.write_bytes(b"<gpx/>")
                artifacts.publish(d["id"], "route.gpx")

                assert draft.load(d["id"])["revision"] == 1
                assert draft.list_all()[0]["id"] == d["id"]
                assert profiles.load("cloud") == saved_profile
                assert profiles.list_all()[0]["naam"] == "cloud"
                assert artifacts.read(d["id"], "route.gpx") == b"<gpx/>"
                assert artifacts.describe(d["id"], "route.gpx")["bytes"] == 6
        finally:
            if previous_tmp is None:
                os.environ.pop("LUSMAKER_TMP", None)
            else:
                os.environ["LUSMAKER_TMP"] = previous_tmp
