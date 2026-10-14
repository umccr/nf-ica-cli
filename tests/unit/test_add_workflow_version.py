"""Unit tests for the add-workflow-version handler."""

import pytest
from pathlib import Path

from nf_ica_cli.config import AppConfig, Workflow, WorkflowVersion, Context, IcaConfig
from nf_ica_cli.handlers.add_workflow_version import handle_add_workflow_version
from nf_ica_cli.yaml_io import load_yaml


@pytest.fixture
def config_repo(tmp_path):
    """Create a minimal config repo with workflows.yaml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    workflows_yaml = config_dir / "workflows.yaml"
    workflows_yaml.write_text(
        "# Workflow definitions\n"
        "workflows:\n"
        "  - name: oncoanalyser\n"
        "    repo_uri: https://github.com/nf-core/oncoanalyser\n"
        "    versions:\n"
        "      - tag: 2.2.0\n"
        "        git_commit_id: b94cbc7\n"
        "        contexts:\n"
        "          - development\n"
        "          - production\n"
    )
    return tmp_path


@pytest.fixture
def base_config(config_repo):
    """Create a base AppConfig for testing."""
    return AppConfig(
        config_repo=config_repo,
        workflows=[
            Workflow(
                name="oncoanalyser",
                repo_uri="https://github.com/nf-core/oncoanalyser",
                versions=[
                    WorkflowVersion(
                        tag="2.2.0",
                        git_commit_id="b94cbc7",
                        contexts=["development", "production"],
                    )
                ],
            )
        ],
        contexts=[
            Context(name="development", description="Dev environment"),
            Context(name="production", description="Prod environment"),
        ],
        ica_config=IcaConfig(tenants=[], default_nextflow_version="24.04.4"),
        pipelines=[],
        patches=[],
    )


@pytest.fixture
def empty_config(config_repo):
    """Create an AppConfig with no existing workflows."""
    # Overwrite workflows.yaml with empty content
    workflows_yaml = config_repo / "config" / "workflows.yaml"
    workflows_yaml.write_text("# Empty workflow definitions\nworkflows: []\n")

    return AppConfig(
        config_repo=config_repo,
        workflows=[],
        contexts=[
            Context(name="development", description="Dev environment"),
            Context(name="production", description="Prod environment"),
        ],
        ica_config=IcaConfig(tenants=[], default_nextflow_version="24.04.4"),
        pipelines=[],
        patches=[],
    )


def _make_args(
    name="oncoanalyser",
    repo_uri="https://github.com/nf-core/oncoanalyser",
    version_tag="2.3.0",
    git_commit_id="abc1234",
    contexts=None,
    ica_nextflow_version="24.04.4",
):
    """Build a docopt-style args dict."""
    if contexts is None:
        contexts = ["development"]
    return {
        "--workflow-name": name,
        "--workflow-repo-uri": repo_uri,
        "--workflow-version-tag": version_tag,
        "--workflow-version-git-commit-id": git_commit_id,
        "--workflow-version-context": contexts,
        "--workflow-ica-nextflow-version": ica_nextflow_version,
    }


class TestAddWorkflowVersionSuccess:
    """Tests for successful version additions."""

    def test_add_version_to_existing_workflow(self, config_repo, base_config):
        """Adding a new version to an existing workflow appends to versions list."""
        args = _make_args(version_tag="2.3.0", git_commit_id="def5678a")

        handle_add_workflow_version(args, base_config, config_repo)

        # Verify the YAML was updated
        data = load_yaml(config_repo / "config" / "workflows.yaml")
        wf = data["workflows"][0]
        assert len(wf["versions"]) == 2
        new_ver = wf["versions"][1]
        assert new_ver["tag"] == "2.3.0"
        assert new_ver["git_commit_id"] == "def5678a"
        assert list(new_ver["contexts"]) == ["development"]
        assert new_ver["ica_nextflow_version"] == "24.04.4"

    def test_add_version_with_multiple_contexts(self, config_repo, base_config):
        """Adding a version with multiple contexts stores all of them."""
        args = _make_args(
            version_tag="3.0.0",
            git_commit_id="1234567",
            contexts=["development", "production"],
        )

        handle_add_workflow_version(args, base_config, config_repo)

        data = load_yaml(config_repo / "config" / "workflows.yaml")
        new_ver = data["workflows"][0]["versions"][1]
        assert list(new_ver["contexts"]) == ["development", "production"]

    def test_create_new_workflow(self, config_repo, empty_config):
        """When workflow doesn't exist, creates a new workflow entry."""
        args = _make_args(
            name="new-workflow",
            repo_uri="https://github.com/example/new-workflow",
            version_tag="1.0.0",
            git_commit_id="abcdef1",
            contexts=["development"],
        )

        handle_add_workflow_version(args, empty_config, config_repo)

        data = load_yaml(config_repo / "config" / "workflows.yaml")
        assert len(data["workflows"]) == 1
        wf = data["workflows"][0]
        assert wf["name"] == "new-workflow"
        assert wf["repo_uri"] == "https://github.com/example/new-workflow"
        assert len(wf["versions"]) == 1
        assert wf["versions"][0]["tag"] == "1.0.0"
        assert wf["versions"][0]["git_commit_id"] == "abcdef1"

    def test_preserves_yaml_comments(self, config_repo, base_config):
        """Comments in workflows.yaml are preserved after modification."""
        args = _make_args(version_tag="2.3.0", git_commit_id="abc1234")

        handle_add_workflow_version(args, base_config, config_repo)

        # Read raw file content and verify comment is preserved
        content = (config_repo / "config" / "workflows.yaml").read_text()
        assert "# Workflow definitions" in content

    def test_no_ica_nextflow_version_omits_field(self, config_repo, base_config):
        """When ica_nextflow_version is empty, the field is not added."""
        args = _make_args(
            version_tag="2.3.0",
            git_commit_id="abc1234",
            ica_nextflow_version="",
        )

        handle_add_workflow_version(args, base_config, config_repo)

        data = load_yaml(config_repo / "config" / "workflows.yaml")
        new_ver = data["workflows"][0]["versions"][1]
        assert "ica_nextflow_version" not in new_ver


class TestAddWorkflowVersionValidation:
    """Tests for validation failures."""

    def test_invalid_git_commit_id_too_short(self, config_repo, base_config):
        """Rejects git commit ID with fewer than 7 characters."""
        args = _make_args(git_commit_id="abc12")

        with pytest.raises(SystemExit) as exc_info:
            handle_add_workflow_version(args, base_config, config_repo)

        assert "VALIDATION" in str(exc_info.value)
        assert "git commit ID" in str(exc_info.value)

    def test_invalid_git_commit_id_invalid_chars(self, config_repo, base_config):
        """Rejects git commit ID with non-hex characters."""
        args = _make_args(git_commit_id="xyz1234")

        with pytest.raises(SystemExit) as exc_info:
            handle_add_workflow_version(args, base_config, config_repo)

        assert "VALIDATION" in str(exc_info.value)

    def test_invalid_context(self, config_repo, base_config):
        """Rejects context values not in defined contexts."""
        args = _make_args(contexts=["staging"])

        with pytest.raises(SystemExit) as exc_info:
            handle_add_workflow_version(args, base_config, config_repo)

        assert "VALIDATION" in str(exc_info.value)
        assert "staging" in str(exc_info.value)

    def test_uri_mismatch(self, config_repo, base_config):
        """Rejects when workflow exists with different repo URI."""
        args = _make_args(
            name="oncoanalyser",
            repo_uri="https://github.com/other/oncoanalyser",
            version_tag="3.0.0",
            git_commit_id="1234567",
        )

        with pytest.raises(SystemExit) as exc_info:
            handle_add_workflow_version(args, base_config, config_repo)

        error_msg = str(exc_info.value)
        assert "URI MISMATCH" in error_msg
        assert "https://github.com/nf-core/oncoanalyser" in error_msg
        assert "https://github.com/other/oncoanalyser" in error_msg

    def test_duplicate_version_tag(self, config_repo, base_config):
        """Rejects when version tag already exists for the workflow."""
        args = _make_args(version_tag="2.2.0", git_commit_id="1234567")

        with pytest.raises(SystemExit) as exc_info:
            handle_add_workflow_version(args, base_config, config_repo)

        error_msg = str(exc_info.value)
        assert "DUPLICATE VERSION" in error_msg
        assert "2.2.0" in error_msg

    def test_validation_before_write(self, config_repo, base_config):
        """Validation errors prevent any file modifications."""
        # Record original content
        workflows_path = config_repo / "config" / "workflows.yaml"
        original_content = workflows_path.read_text()

        args = _make_args(git_commit_id="invalid!")

        with pytest.raises(SystemExit):
            handle_add_workflow_version(args, base_config, config_repo)

        # File should be unchanged
        assert workflows_path.read_text() == original_content
