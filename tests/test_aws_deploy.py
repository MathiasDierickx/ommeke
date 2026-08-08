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
    vercel = _read("web/vercel.json")
    assert '"outputDirectory": "out"' in vercel

    pack = _read(".github/workflows/build-region-pack.yml")
    assert "workflow_dispatch:" in pack
    assert "LUSMAKER_PACK_UPLOAD" in pack
    assert "region-packs/" in pack
