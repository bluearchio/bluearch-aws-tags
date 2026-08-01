from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys

from tag_manager_cli.commands import ai_commands, lifecycle_commands
from tag_manager_cli.integrations.aws_tools import AWSTools
from tag_manager_cli.modules import multi_account_discovery as multi_account_module
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
