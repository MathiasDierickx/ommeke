"""Offline controle van de opt-in warme router en echte entrypointvertakkingen."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def test_entrypoint_preserves_external_url_without_starting_or_copying_graph():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        # Vang exec op: uvicorn schrijft alleen de gekozen omgeving.
        uvicorn = bin_dir / "uvicorn"
        uvicorn.write_text(f'''#!{sys.executable}
import json, os
print(json.dumps(dict(os.environ)))
''')
        uvicorn.chmod(0o755)
        python = bin_dir / "python"
        python.symlink_to(sys.executable)
        env = {key: value for key, value in os.environ.items() if not key.startswith("LUSMAKER_")}
        env.update(PATH=f"{bin_dir}:{env['PATH']}", LUSMAKER_REGION="offline",
                   LUSMAKER_STATIC_HOME=str(root / "missing-pack"),
                   LUSMAKER_WRITABLE_HOME=str(root / "runtime"),
                   LUSMAKER_GH_FAILED_MARKER=str(root / "stale.failed"))
        for url in ("https://example.cloudfront.net", "http://localhost.example.invalid", "https://127.0.0.1.example.invalid"):
            result = subprocess.run(["sh", str(ROOT / "deploy/aws/entrypoint.sh")],
                                    env={**env, "LUSMAKER_GH_URL": url}, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            captured = json.loads(result.stdout)
            assert captured["LUSMAKER_GH_URL"] == url
            assert captured["LUSMAKER_GH_STARTUP_WAIT_S"] == "840"
            assert "LUSMAKER_GH_FAILED_MARKER" not in captured
            assert not (root / "runtime").exists()
        for url in ("http://localhost:8989", "http://127.0.0.1:8989", "http://[::1]:8989", None):
            local_env = dict(env)
            if url:
                local_env["LUSMAKER_GH_URL"] = url
            result = subprocess.run(["sh", str(ROOT / "deploy/aws/entrypoint.sh")],
                                    env=local_env, capture_output=True, text=True)
            assert result.returncode == 1
            assert "mist een voorbereid GraphHopper-regiopack" in result.stderr
            assert not result.stdout


def test_warm_service_is_conditional_and_origin_requires_the_client_secret():
    tf = (ROOT / "infra/terraform/gh_service.tf").read_text()
    import re
    blocks = re.split(r'(?m)^(?:data|resource) "', tf)[1:]
    assert blocks
    for block in blocks:
        assert "count" in block and "var.gh_service_enabled ? 1 : 0" in block
    assert 'name  = "com.amazonaws.global.cloudfront.origin-facing"' in tf
    assert 'prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront[0].id]' in tf
    assert 'headers      = ["X-Ommeke-Origin", "Content-Type"]' in tf
    assert 'custom_header' not in tf  # CloudFront geeft anonieme bezoekers geen geheim.
    assert 'origin_protocol_policy = "http-only"' in tf
    assert 'cloudfront_default_certificate = true' in tf
    for ttl in ("min_ttl", "default_ttl", "max_ttl"):
        assert re.search(rf'{ttl}\s*= 0', tf)
    variables = (ROOT / "infra/terraform/variables.tf").read_text()
    assert re.search(r'variable "gh_service_enabled".*?default\s*= false', variables, re.S)
    main = (ROOT / "infra/terraform/main.tf").read_text()
    assert 'var.gh_service_enabled ? {' in main
    assert 'LUSMAKER_GH_ORIGIN_SECRET = random_password.gh_origin[0].result' in main
    template = (ROOT / "infra/terraform/gh-user-data.sh.tftpl").read_text()
    assert 'if ($http_x_ommeke_origin != "${origin_secret}") { return 403; }' in template
    assert '127.0.0.1:8989:8989' in template
    assert 'israelhikingmap/graphhopper:11.0' in template
    assert '- profile: quiet' in template and '- profile: trail' in template
    assert 'mkfs' in template and 'if ! blkid' in template
    assert 'set -x' not in '\n'.join(line for line in template.splitlines() if not line.startswith('#'))


def test_warm_service_workflow_and_bootstrap_cover_deployment_and_rollback():
    workflow = (ROOT / ".github/workflows/deploy-aws.yml").read_text()
    assert "TF_VAR_gh_service_enabled: ${{ vars.GH_SERVICE_ENABLED || 'false' }}" in workflow
    assert 'TF_VAR_gh_pack_bucket: ${{ vars.TF_STATE_BUCKET }}' in workflow
    assert '$HEALTH?router=1' in workflow
    bootstrap = (ROOT / "infra/bootstrap/main.tf").read_text()
    assert '"ec2:*"' not in bootstrap and '"cloudfront:*"' not in bootstrap
    assert '"ec2:RunInstances"' in bootstrap and '"ec2:TerminateInstances"' in bootstrap
    assert '"cloudfront:DeleteDistribution"' in bootstrap
    assert '"iam:PassedToService"' in bootstrap and '["ec2.amazonaws.com"]' in bootstrap
    assert 'instance-profile/${var.project_name}-*-gh' in bootstrap
