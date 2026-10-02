"""Statische regressietests voor de serverless deployment-invarianten."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_terraform_has_scale_to_zero_without_fixed_network_compute():
    terraform = _read("infra/terraform/main.tf")
    assert 'resource "aws_lambda_function" "app"' in terraform
    assert 'package_type                   = "Image"' in terraform
    assert "reserved_concurrent_executions = var.max_concurrency" in terraform
    assert 'invoke_mode        = "RESPONSE_STREAM"' in terraform
    assert "provisioned_concurrent_executions" not in terraform
    assert 'billing_mode = "PAY_PER_REQUEST"' in terraform
    assert 'resource "aws_dynamodb_table" "chat"' in terraform
    assert 'bedrock:InvokeModel' in terraform
    for fixed_cost_resource in (
        'resource "aws_nat_gateway"',
        'resource "aws_ecs_service"',
        'resource "aws_instance"',
        'resource "aws_apigatewayv2_api"',
        'resource "aws_efs_file_system"',
    ):
        assert fixed_cost_resource not in terraform


def test_container_and_pack_pin_the_same_graphhopper_release():
    dockerfile = _read("deploy/aws/Dockerfile")
    entrypoint = _read("deploy/aws/entrypoint.sh")
    compose = _read("docker-compose.yml")
    config = _read("lusmaker/config.py")
    assert "israelhikingmap/graphhopper:11.0" in dockerfile
    assert "israelhikingmap/graphhopper:11.0" in compose
    assert "israelhikingmap/graphhopper:11.0" in config
    assert "AWS_LWA_ASYNC_INIT=true" in dockerfile
    assert "find /opt/graphhopper" in entrypoint
    assert 'JAR="$GRAPH_JAR"' in entrypoint
    assert "-Xms256m -Xmx2g" in entrypoint


def test_workflows_are_valid_yaml_and_deploy_by_digest_with_oidc():
    workflows = ROOT / ".github" / "workflows"
    for path in workflows.glob("*.yml"):
        assert isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict)

    deploy = _read(".github/workflows/deploy-aws.yml")
    assert "id-token: write" in deploy
    assert "aws-actions/configure-aws-credentials@" in deploy
    assert "@sha256:" not in deploy  # de runtime-digest komt uit ECR, niet hardcoded
    assert "imageDigest" in deploy
    assert "provenance: false" in deploy
    assert "lusmaker.tfplan" in deploy

    assert not (workflows / "deploy-vercel.yml").exists()
    next_config = _read("web/next.config.ts")
    assert 'output: "export"' not in next_config
    assert (ROOT / "web/app/chats/[conversationId]/page.tsx").is_file()
    assert (ROOT / "web/app/routes/[routeId]/page.tsx").is_file()

    pack = _read(".github/workflows/build-region-pack.yml")
    assert "workflow_dispatch:" in pack
    assert "LUSMAKER_PACK_UPLOAD" in pack
    assert "region-packs/" in pack


def test_deployment_requires_all_checks_for_the_same_commit():
    ci = yaml.safe_load(_read('.github/workflows/ci.yml'))
    deploy = yaml.safe_load(_read('.github/workflows/deploy-aws.yml'))
    assert 'workflow_call' in ci.get('on', ci.get(True))
    assert {'test', 'terraform', 'web'} <= set(ci['jobs'])
    assert deploy['jobs']['checks']['uses'] == './.github/workflows/ci.yml'
    assert deploy['jobs']['deploy']['needs'] == 'checks'
    steps = deploy['jobs']['deploy']['steps']
    guard = next(i for i, step in enumerate(steps) if 'achterhaalde' in step.get('name', ''))
    credentials = next(i for i, step in enumerate(steps) if 'configure-aws-credentials' in step.get('uses', ''))
    assert guard < credentials
    assert '$GITHUB_SHA' in steps[guard]['run']


def test_cloud_sources_are_visible_to_tenant_engine_without_graph_changes():
    import json
    import tempfile
    from deploy.aws.prepare_sources import prepare
    from lusmaker import config, draft, route_evidence, route_sources
    from tests.test_route_sources import fixture_fetch

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with route_sources._home(root / "local"):
            result = route_sources.sync(root / "sources", fetcher=fixture_fetch)
        destination = root / "cloud"
        graph = destination / "regions/vlaanderen/gh/config.yml"
        graph.parent.mkdir(parents=True)
        graph.write_text("bestaande graphconfig")
        (destination / "regions.json").write_text(json.dumps({
            "default": "vlaanderen", "regions": {"vlaanderen": {
                "slug": "vlaanderen", "geofabrik": "europe/belgium",
                "bbox": [50.67, 2.53, 51.51, 5.94], "gh_port": 8989,
            }}
        }))
        prepared = prepare(Path(result["build"]), destination)
        assert prepared["build_id"] == result["build_id"]
        assert graph.read_text() == "bestaande graphconfig"
        public_root = destination / "regions/vlaanderen/cache/route_sources"
        # Lambda leest als een andere gebruiker dan de imagebuilder. Een
        # eigenaarstest alleen mist de 700/600-rechten van tijdelijke bestanden.
        for path in [public_root, *public_root.rglob("*")]:
            assert path.stat().st_mode & 0o004, path
            if path.is_dir():
                assert path.stat().st_mode & 0o001, path
        with route_sources._home(destination), config.user_scope("cloud-user"):
            assert destination in route_evidence.database_path().parents
            assert route_evidence.pack_status() == {
                "build_id": result["build_id"], "features": 5, "layers": 18,
            }
            score = draft._candidate_surface_components([
                {"coords": [(50.8, 3.7), (50.8, 3.704)]}
            ])
            assert score["populair"] > 0
        # Herhaalde staging blijft op dezelfde gecontroleerde versie staan.
        assert prepare(Path(result["build"]), destination)["build_id"] == result["build_id"]
        pointer = destination / "regions/vlaanderen/cache/route_sources/current.json"
        assert pointer.stat().st_mode & 0o004
        assert json.loads(pointer.read_text())["build_id"] == result["build_id"]


def test_cloud_sources_reject_unverified_payload_before_activation():
    import tempfile
    from deploy.aws.prepare_sources import prepare
    from lusmaker import route_sources
    from tests.test_route_sources import fixture_fetch, expect_error

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with route_sources._home(root / "local"):
            result = route_sources.sync(root / "sources", fetcher=fixture_fetch)
        build = Path(result["build"])
        (build / "manifest.json").write_text('{}')
        expect_error(lambda: prepare(build, root / "cloud"), "gewijzigd")
        assert not (root / "cloud").exists()
