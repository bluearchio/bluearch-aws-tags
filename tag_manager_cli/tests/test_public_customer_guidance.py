from contextlib import nullcontext
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from tag_manager_cli.commands import (
    account_commands,
    ai_commands,
    cost_commands,
    lifecycle_commands,
)
from tag_manager_cli.integrations.aws_assistant import BedrockAWSAssistant
from tag_manager_cli.integrations.aws_tools import AWSTools
from tag_manager_cli.modules import discovery as discovery_module
from tag_manager_cli.modules import multi_account_discovery as multi_account_module
from tag_manager_cli.modules.finops.cur_setup import CURConfiguration, CURSetup
from tag_manager_cli.services.slack_notification_service import SlackConfig, SlackNotificationService
from tag_manager_cli.utils.command_suggestions import CommandSuggestions


class _EmptyQuery:
    def count(self):
        return 0


class _EmptySession:
    def query(self, _model):
        return _EmptyQuery()


def test_empty_lifecycle_inventory_prints_public_scan_command(monkeypatch, capsys):
    monkeypatch.setattr(lifecycle_commands, "_get_db_session", lambda: nullcontext(_EmptySession()))

    assert lifecycle_commands._check_resources_exist() is False

    output = capsys.readouterr().out
    assert "bluearch-aws-tags lifecycle scan" in output
    assert "tag-manager lifecycle scan" not in output


def test_ai_access_success_prints_public_chat_command(monkeypatch, capsys):
    class Bedrock:
        def list_foundation_models(self, **_kwargs):
            return {"modelSummaries": [{"modelId": "model", "modelName": "Claude", "modelLifecycle": {"status": "ACTIVE"}}]}

    class Runtime:
        def converse(self, **_kwargs):
            return {"output": {"message": {"content": []}}}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda service, **_kwargs: Bedrock() if service == "bedrock" else Runtime())

    ai_commands.check_access(region="us-east-1")

    output = capsys.readouterr().out
    assert "bluearch-aws-tags ask chat" in output
    assert "tag-manager ask chat" not in output


def test_lifecycle_wizard_prints_registered_multi_account_command(monkeypatch, capsys):
    monkeypatch.setattr(AWSTools, "list_available_accounts", staticmethod(lambda: []))
    monkeypatch.setattr(lifecycle_commands.Confirm, "ask", lambda *_args, **_kwargs: True)

    lifecycle_commands.wizard_command()

    output = capsys.readouterr().out
    assert "bluearch-aws-tags setup multi-account" in output
    assert "setup multi-accounts" not in output


def test_customer_help_commands_use_registered_public_syntax():
    content = "\n".join(
        AWSTools.get_cli_help(topic)["content"]
        for topic in ("commands", "cost", "tags", "accounts")
    )
    expected_commands = (
        ("setup", "validate"),
        ("discover", "all"),
        ("lifecycle", "scan"),
        ("lifecycle", "review"),
        ("lifecycle", "set-ttl"),
        ("setup", "multi-account"),
        ("setup", "multi-account", "--validate-only"),
        ("setup", "multi-account", "--complete"),
        ("cost", "setup", "detect"),
        ("cost", "setup", "create"),
        ("cost", "summary"),
        ("cost", "ec2", "instances"),
        ("cost", "compare", "this-month", "last-month"),
        ("setup", "database", "--force"),
    )

    assert "bluearch-aws-tags lifecycle scan" in content
    assert "bluearch-aws-tags setup multi-account" in content
    assert "bluearch-aws-tags cost ec2 instances" in content
    assert "bluearch-aws-tags cost compare this-month last-month" in content
    assert "bluearch-aws-tags tags " not in content
    assert "bluearch-aws-tags account " not in content
    assert "cost ec2 --view" not in content
    assert "cost compare --periods" not in content

    root = Path(__file__).resolve().parents[2]
    for command in expected_commands:
        result = subprocess.run(
            [sys.executable, "-m", "tag_manager_cli.main", *command, "--help"],
            cwd=root,
            env={
                **os.environ,
                "PYTHONPATH": os.fspath(root),
                "TAG_MANAGER_SKIP_UPDATE_CHECK": "1",
                "TAG_MANAGER_SUPPRESS_STARTUP_STATE": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (command, result.stdout, result.stderr)


def test_first_time_suggestions_only_advertise_registered_commands():
    commands = [item["cmd"] for item in CommandSuggestions().suggestions_map["first_time"]]

    assert "setup validate" in commands
    assert "system validate" not in commands


def test_all_contextual_suggestions_use_registered_public_roots():
    from tag_manager_cli.main import app

    root_command = typer.main.get_command(app)
    registered = set(root_command.commands)
    allowed_root_options = {"--help", "--version"}
    findings = []

    for context, suggestions in CommandSuggestions().suggestions_map.items():
        for suggestion in suggestions:
            command = suggestion["cmd"]
            parts = shlex.split(command)
            root = parts[0] if parts else ""
            if root not in registered and root not in allowed_root_options:
                findings.append(f"{context}: {command}")
                continue

            current = root_command
            for token in parts:
                if token.startswith("-") or not getattr(current, "commands", None):
                    break
                if token not in current.commands:
                    findings.append(f"{context}: {command} (missing {token})")
                    break
                current = current.commands[token]

    assert "tags" not in registered
    assert CommandSuggestions.PUBLIC_COMMAND_ROOTS <= registered | allowed_root_options
    assert findings == []


def test_suggestion_renderer_rejects_unregistered_bare_namespace():
    with pytest.raises(ValueError, match="Unregistered public command suggestion"):
        CommandSuggestions._public_command("tags scan")


@pytest.mark.parametrize(
    ("context", "data", "expected_command"),
    (
        (
            "tags.scan",
            {"untagged_count": 75, "top_service": "ec2"},
            "lifecycle set-ttl --services ec2 --dry-run",
        ),
        ("tags.scan", {"untagged_count": 4}, "lifecycle wizard"),
        (
            "workers.discover",
            {"success": True, "discovered_count": 8},
            "lifecycle scan",
        ),
        (
            "tags.apply",
            {"success": True, "resources_tagged": 3},
            "lifecycle review --include-active",
        ),
        (
            "system.validate",
            {"all_valid": False, "failed_checks": ["AWS credentials"]},
            "setup aws",
        ),
        (
            "system.validate",
            {"all_valid": False, "failed_checks": ["Docker runtime"]},
            "setup doctor",
        ),
        ("workers.health", {"issues_fixed": 2}, "setup validate"),
        ("update.check", {"updates_available": 1}, "update --yes"),
    ),
    ids=(
        "many-untagged",
        "few-untagged",
        "resources-discovered",
        "resources-tagged",
        "aws-validation-failure",
        "docker-validation-failure",
        "worker-fixes",
        "update-available",
    ),
)
def test_dynamic_suggestions_render_registered_public_commands(
    context,
    data,
    expected_command,
    capsys,
):
    from tag_manager_cli.main import app

    suggestions = CommandSuggestions()
    suggestions.console = Console(width=240)
    contextual = suggestions._get_contextual_suggestions(context, data)

    assert contextual[0]["cmd"] == expected_command

    parts = shlex.split(expected_command)
    current = typer.main.get_command(app)
    index = 0
    while getattr(current, "commands", None):
        token = parts[index]
        assert token in current.commands
        current = current.commands[token]
        index += 1

    with current.make_context(current.name or "command", parts[index:]):
        pass

    suggestions.show_suggestions(context, data=data, show_tip=False)
    output = capsys.readouterr().out
    assert f"bluearch-aws-tags {expected_command}" in output
    for unavailable_root in (
        "accounts",
        "database",
        "docker",
        "service",
        "system",
        "tag",
        "tags",
        "tasks",
        "workers",
    ):
        assert f"bluearch-aws-tags {unavailable_root} " not in output


def test_all_prefixed_suggestion_renderers_emit_only_public_command_roots(capsys):
    suggestions = CommandSuggestions()

    for context in suggestions.suggestions_map:
        suggestions.show_suggestions(context, show_tip=False)
    for error_context in ("aws_auth", "database", "workers", "docker", "permission"):
        suggestions.show_error_recovery(error_context, "test error")

    output = capsys.readouterr().out
    for unavailable_root in (
        "accounts",
        "database",
        "docker",
        "service",
        "system",
        "tag",
        "tags",
        "tasks",
        "workers",
    ):
        assert f"bluearch-aws-tags {unavailable_root} " not in output
    assert "bluearch-aws-tags bluearch-aws-tags" not in output
    assert "bluearch-aws-tags aws " not in output


def test_workflow_suggestions_use_fully_qualified_public_commands(capsys):
    suggestions = CommandSuggestions()

    for workflow_type in suggestions.workflow_suggestions:
        suggestions.show_suggestions(
            "not-a-context",
            show_workflow=True,
            workflow_type=workflow_type,
            show_tip=False,
        )

    output = capsys.readouterr().out
    assert "bluearch-aws-tags lifecycle" in output
    assert "bluearch-aws-tags setup" in output
    assert "'tags " not in output
    assert "'workers " not in output
    assert "'system " not in output


def test_discovery_compliance_guidance_uses_registered_policy_command(capsys):
    discovery_module._display_compliance_summary(
        discovery_module.console,
        {
            "required_tags": ["Environment", "Owner"],
            "from_org_policy": True,
            "total_compliant": 1,
            "total_noncompliant": 1,
            "by_service": {
                "ec2": {"compliant": 1, "noncompliant": 1},
            },
        },
    )

    output = capsys.readouterr().out
    assert "bluearch-aws-tags policy check-compliance --details" in output
    assert "'tags scan'" not in output


def test_ai_system_prompt_only_recommends_registered_public_namespaces():
    assistant = BedrockAWSAssistant(model_id="test-model")
    prompt = assistant._get_system_prompt()[0]["text"]

    assert "lifecycle scan" in prompt
    assert "policy check-compliance" in prompt
    assert "tags scan" not in prompt


def test_dormant_account_help_redirects_to_registered_public_workflow(capsys):
    account_commands.show_accounts_help()

    output = capsys.readouterr().out
    assert "bluearch-aws-tags setup multi-account --complete" in output
    assert "bluearch-aws-tags lifecycle wizard" in output
    assert "tags apply" not in output
    assert "accounts setup" not in output


def test_empty_multi_account_discovery_prints_registered_setup_command(monkeypatch, capsys):
    discovery = multi_account_module.multi_account_discovery
    monkeypatch.setattr(discovery, "get_enabled_accounts", lambda: [])
    monkeypatch.setattr(
        multi_account_module.aws_auth,
        "get_caller_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("no identity")),
    )

    result = discovery.discover_all_accounts(show_progress=False, save_to_database=False)

    assert result.total_accounts == 0
    output = capsys.readouterr().out
    assert "bluearch-aws-tags setup multi-account --complete" in output
    assert "bluearch-aws-tags accounts" not in output


def test_slack_expiration_warning_contains_public_review_command():
    service = SlackNotificationService()
    service._config = SlackConfig(webhook_url="https://hooks.slack.com/services/test")
    payloads = []
    service._send_webhook = lambda _url, payload: payloads.append(payload)

    service.send_expiration_warning(
        [{"service_name": "ec2", "resource_id": "i-123", "region": "us-east-1"}],
        days_until_expiry=3,
    )

    texts = [block.get("text", {}).get("text", "") for block in payloads[0]["blocks"]]
    assert any("bluearch-aws-tags lifecycle review" in text for text in texts)
    assert all("tag-manager lifecycle review" not in text for text in texts)


def test_slack_batch_summary_contains_public_lifecycle_commands():
    service = SlackNotificationService()
    service._config = SlackConfig(webhook_url="https://hooks.slack.com/services/test")
    payloads = []
    service._send_webhook = lambda _url, payload: payloads.append(payload)

    service.send_batch_summary({"total_with_ttl": 1, "expired": 1})

    texts = [block.get("text", {}).get("text", "") for block in payloads[0]["blocks"]]
    assert any("bluearch-aws-tags lifecycle review" in text for text in texts)
    assert all("tag-manager lifecycle" not in text for text in texts)


@pytest.mark.parametrize("action", ["detect", "validate"])
def test_pending_cost_setup_guidance_uses_registered_public_detect(
    monkeypatch,
    capsys,
    action,
):
    pending = SimpleNamespace(status="pending")
    monkeypatch.setattr(CURSetup, "detect_existing_cur", lambda *_args, **_kwargs: pending)

    try:
        cost_commands.cost_setup.__wrapped__(
            action=action,
            bucket=None,
            database=None,
            table=None,
            force=False,
        )
    except typer.Exit as exc:
        assert exc.exit_code == 0

    output = capsys.readouterr().out
    assert "bluearch-aws-tags cost setup detect" in output
    assert "cost setup status" not in output


def test_existing_pending_managed_cur_prints_public_detect_command(capsys):
    pending = SimpleNamespace(report_name="tag-manager-cur", status="pending")

    class Setup:
        def detect_existing_cur(self):
            return pending

        def display_cur_status(self, _config):
            return None

    cost_commands._deploy_cur(Setup())

    output = capsys.readouterr().out
    assert "bluearch-aws-tags cost setup detect" in output


def test_cur_detection_pending_state_prints_public_detect_command(monkeypatch, capsys):
    pending = CURConfiguration(
        account_id="123456789012",
        report_name="tag-manager-cur",
        s3_bucket="cur-bucket",
        s3_prefix="reports",
        athena_database="",
        athena_table="",
        status="pending",
    )
    setup = CURSetup()
    monkeypatch.setattr(
        setup,
        "_get_client",
        lambda _service: SimpleNamespace(
            get_caller_identity=lambda: {"Account": "123456789012"}
        ),
    )
    monkeypatch.setattr(
        setup,
        "_find_cur_reports",
        lambda: [
            {
                "ReportName": "tag-manager-cur",
                "S3Bucket": "cur-bucket",
                "S3Prefix": "reports",
            }
        ],
    )
    monkeypatch.setattr(setup, "_find_cur_databases", lambda: [])
    monkeypatch.setattr(setup, "_match_cur_config", lambda *_args: pending)

    assert setup.detect_existing_cur(force_refresh=True) is pending

    output = capsys.readouterr().out
    assert "bluearch-aws-tags cost setup detect" in output


def test_aws_tools_pending_cur_guidance_uses_registered_public_detect(monkeypatch):
    pending = SimpleNamespace(status="pending")
    monkeypatch.setattr(CURSetup, "detect_existing_cur", lambda *_args, **_kwargs: pending)

    result = AWSTools.query_cur_costs("show monthly cost")

    assert result["cur_available"] is False
    assert "bluearch-aws-tags cost setup detect" in result["suggestion"]
    assert 'Run "cost setup detect"' not in result["suggestion"]


def test_cur_only_fallback_guidance_uses_registered_public_detect(monkeypatch):
    from tag_manager_cli.modules.finops.cur_client import CostDataSource

    pending = SimpleNamespace(status="pending")
    messages = []
    monkeypatch.setattr(CURSetup, "detect_existing_cur", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(
        CostDataSource,
        "get_source",
        classmethod(lambda _cls, config: object() if config is pending else None),
    )
    monkeypatch.setattr(cost_commands, "print_safe", messages.append)
    monkeypatch.setattr(cost_commands, "print_warning", messages.append)

    cost_commands.cost_accounts.__wrapped__(
        start_date=None,
        end_date=None,
        include_services=False,
        format_type="table",
    )

    output = "\n".join(messages)
    assert "bluearch-aws-tags cost setup detect" in output
    assert "Run 'cost setup detect'" not in output
