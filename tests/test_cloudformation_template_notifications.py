from tag_manager_cli.services.cloudformation_template_notifications import (
    compare_versions,
    detect_deprecated_cloudformation_templates,
    extract_template_version,
    notify_deprecated_cloudformation_templates,
)


def test_compare_versions_handles_v_prefix_and_missing_patch():
    assert compare_versions("v0.12.3", "v0.12.4") == -1
    assert compare_versions("0.12", "v0.12.0") == 0
    assert compare_versions("v0.13.0", "v0.12.9") == 1
    assert compare_versions("__CLI_VERSION__", "v0.12.4") is None


def test_extract_template_version_prefers_tag_manager_cli_version():
    template = {
        "Metadata": {
            "TagManagerCLI": {
                "Version": "v0.12.3",
                "CLIVersion": "v0.12.4",
            }
        }
    }

    assert extract_template_version(template) == ("v0.12.4", "CLIVersion", "TagManagerCLI")


def test_extract_template_version_accepts_shared_bluearch_metadata():
    template = {
        "Metadata": {
            "BlueArchCLI": {
                "CLIVersion": "v0.12.2",
            }
        }
    }

    assert extract_template_version(template) == ("v0.12.2", "CLIVersion", "BlueArchCLI")


def test_notify_skips_local_version_without_aws_calls():
    class FailingSession:
        region_name = "us-east-1"

        def client(self, *args, **kwargs):
            raise AssertionError("AWS should not be called for LOCAL version")

    result = notify_deprecated_cloudformation_templates(
        session=FailingSession(),
        current_version="LOCAL",
    )

    assert result.status == "skipped_local_version"


def test_detects_outdated_stack_and_stackset_templates():
    findings = detect_deprecated_cloudformation_templates(
        session=FakeSession(),
        current_version="v0.12.4",
        regions=["us-east-1"],
    )

    assert [(finding.kind, finding.name, finding.deployed_version) for finding in findings] == [
        ("stack", "TagManagerCLI-Management-Account-Resources", "v0.12.3"),
        ("stackset", "BlueArchCLI-CrossAccount-Infrastructure", "v0.12.2"),
    ]
    assert [finding.setup_path for finding in findings] == [
        "/setup",
        "/setup/multi-account",
    ]


def test_detects_tag_only_cur_and_local_stackset_templates():
    findings = detect_deprecated_cloudformation_templates(
        session=FakeTagOnlySession(),
        current_version="v0.12.4",
        regions=["us-east-1"],
    )

    assert [(finding.kind, finding.name, finding.deployed_version, finding.setup_path) for finding in findings] == [
        ("stack", "TagManagerCUR", "v0.12.1", "/cost"),
        ("stackset", "TagManagerCLI-CrossAccount-Infrastructure", "LOCAL", "/setup/multi-account"),
    ]


class FakeSession:
    region_name = "us-east-1"

    def client(self, service_name, region_name=None, config=None):
        assert service_name == "cloudformation"
        return FakeCloudFormationClient()


class FakeCloudFormationClient:
    def get_paginator(self, name):
        return FakePaginator(name)

    def describe_stack_set(self, StackSetName):
        return {
            "StackSet": {
                "TemplateBody": {
                    "Metadata": {
                        "BlueArchCLI": {
                            "CLIVersion": "v0.12.2",
                        }
                    }
                }
            }
        }

    def get_template(self, StackName, TemplateStage="Original"):
        return {
            "TemplateBody": {
                "Metadata": {
                    "TagManagerCLI": {
                        "CLIVersion": "v0.12.3",
                    }
                }
            }
        }


class FakePaginator:
    def __init__(self, name):
        self.name = name

    def paginate(self, **kwargs):
        if self.name == "list_stack_sets":
            return [{
                "Summaries": [
                    {"StackSetName": "BlueArchCLI-CrossAccount-Infrastructure"},
                    {"StackSetName": "Unrelated"},
                ]
            }]
        if self.name == "describe_stacks":
            return [{
                "Stacks": [
                    {"StackName": "TagManagerCLI-Management-Account-Resources", "Tags": []},
                    {"StackName": "Unrelated", "Tags": []},
                ]
            }]
        raise AssertionError(f"unexpected paginator: {self.name}")


class FakeTagOnlySession:
    region_name = "us-east-1"

    def client(self, service_name, region_name=None, config=None):
        assert service_name == "cloudformation"
        return FakeTagOnlyCloudFormationClient()


class FakeTagOnlyCloudFormationClient:
    def get_paginator(self, name):
        return FakeTagOnlyPaginator(name)

    def describe_stack_set(self, StackSetName):
        return {
            "StackSet": {
                "TemplateBody": {},
                "Tags": [{"Key": "bluearch:version", "Value": "LOCAL"}],
            }
        }

    def get_template(self, StackName, TemplateStage="Original"):
        return {"TemplateBody": {}}


class FakeTagOnlyPaginator:
    def __init__(self, name):
        self.name = name

    def paginate(self, **kwargs):
        if self.name == "list_stack_sets":
            return [{"Summaries": [{"StackSetName": "TagManagerCLI-CrossAccount-Infrastructure"}]}]
        if self.name == "describe_stacks":
            return [{
                "Stacks": [{
                    "StackName": "TagManagerCUR",
                    "Tags": [{"Key": "bluearch:version", "Value": "v0.12.1"}],
                }]
            }]
        raise AssertionError(f"unexpected paginator: {self.name}")
