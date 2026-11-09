"""Unit tests for nf_ica_cli.config module."""

import pytest
from pathlib import Path

from nf_ica_cli.config import (
    AppConfig,
    Context,
    IcaConfig,
    IcaProject,
    OidcAuth,
    PipelineEntry,
    Tenant,
    Workflow,
    WorkflowVersion,
    find_config_repo,
    load_and_validate_config,
)
from nf_ica_cli.patches import PatchEntry


class TestFindConfigRepo:
    """Tests for find_config_repo()."""

    def test_finds_config_repo_in_current_dir(self, tmp_path, monkeypatch):
        """When config/workflows.yaml exists in CWD, returns CWD."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "workflows.yaml").write_text("workflows: []")

        monkeypatch.chdir(tmp_path)
        result = find_config_repo()
        assert result == tmp_path

    def test_finds_config_repo_in_parent_dir(self, tmp_path, monkeypatch):
        """When config/workflows.yaml exists in a parent dir, finds it."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "workflows.yaml").write_text("workflows: []")

        # Create nested subdirectory
        nested = tmp_path / "sub" / "deep"
        nested.mkdir(parents=True)

        monkeypatch.chdir(nested)
        result = find_config_repo()
        assert result == tmp_path

    def test_raises_system_exit_when_not_found(self, tmp_path, monkeypatch):
        """When no config repo exists in tree, raises SystemExit."""
        # Use a directory with no config/workflows.yaml anywhere above
        isolated = tmp_path / "isolated"
        isolated.mkdir()

        monkeypatch.chdir(isolated)
        with pytest.raises(SystemExit) as exc_info:
            find_config_repo()

        error_msg = str(exc_info.value)
        assert "CONFIG NOT FOUND" in error_msg
        assert "config/workflows.yaml" in error_msg

    def test_error_message_lists_expected_structure(self, tmp_path, monkeypatch):
        """Error message includes expected directory structure."""
        isolated = tmp_path / "isolated"
        isolated.mkdir()

        monkeypatch.chdir(isolated)
        with pytest.raises(SystemExit) as exc_info:
            find_config_repo()

        error_msg = str(exc_info.value)
        assert "config/contexts.yaml" in error_msg
        assert "config/ica_config.yaml" in error_msg
        assert "config/ica_pipelines.yaml" in error_msg
        assert "config/patches.yaml" in error_msg
        assert "patches/" in error_msg


class TestLoadAndValidateConfig:
    """Tests for load_and_validate_config()."""

    @pytest.fixture
    def config_repo(self, tmp_path):
        """Create a minimal valid config repo structure."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "workflows.yaml").write_text(
            "workflows:\n"
            "  - name: oncoanalyser\n"
            "    repo_uri: https://github.com/nf-core/oncoanalyser\n"
            "    versions:\n"
            "      - tag: '2.2.0'\n"
            "        git_commit_id: b94cbc7\n"
            "        contexts:\n"
            "          - development\n"
            "          - production\n"
        )

        (config_dir / "contexts.yaml").write_text(
            "contexts:\n"
            "  - name: production\n"
            "    description: The production environment\n"
            "  - name: development\n"
            "    description: The development environment\n"
        )

        (config_dir / "ica_config.yaml").write_text(
            "tenants:\n"
            "  - name: umccr-prod\n"
            "    id: 1555b441-c3be-40b0-a8f0-fb9dc7500545\n"
            "    projects:\n"
            "      - id: ea19a3f5-ec7c-4940-a474-c31cd91dbad4\n"
            "        name: development\n"
            "        oidc_auth:\n"
            "          - aws_role_arn: arn:aws:iam::123456789012:role/test\n"
            "            secret_arn: arn:aws:secretsmanager:us-east-1:123456789012:secret:test\n"
            "        contexts:\n"
            "          - development\n"
            "default_nextflow_version: '25.10'\n"
        )

        (config_dir / "ica_pipelines.yaml").write_text(
            "pipelines:\n"
            "  - workflow_name: oncoanalyser\n"
            "    workflow_version: '2.2.0'\n"
            "    git_commit_id: b94cbc7\n"
            "    pipeline_id: abc-123\n"
            "    release_status: DRAFT\n"
            "    tenants:\n"
            "      - umccr-prod\n"
            "    contexts:\n"
            "      - development\n"
            "    patch_files: []\n"
            "    ica_nextflow_version: '25.10'\n"
        )

        return tmp_path

    def test_loads_all_config_files(self, config_repo):
        """Successfully loads and parses all config YAML files."""
        result = load_and_validate_config(config_repo)

        assert isinstance(result, AppConfig)
        assert result.config_repo == config_repo

    def test_parses_workflows(self, config_repo):
        """Workflows are correctly parsed into dataclasses."""
        result = load_and_validate_config(config_repo)

        assert len(result.workflows) == 1
        wf = result.workflows[0]
        assert wf.name == "oncoanalyser"
        assert wf.repo_uri == "https://github.com/nf-core/oncoanalyser"
        assert len(wf.versions) == 1

        ver = wf.versions[0]
        assert ver.tag == "2.2.0"
        assert ver.git_commit_id == "b94cbc7"
        assert ver.contexts == ["development", "production"]
        assert ver.ica_nextflow_version is None

    def test_parses_contexts(self, config_repo):
        """Contexts are correctly parsed into dataclasses."""
        result = load_and_validate_config(config_repo)

        assert len(result.contexts) == 2
        names = [c.name for c in result.contexts]
        assert "production" in names
        assert "development" in names

    def test_parses_ica_config(self, config_repo):
        """ICA config is correctly parsed with tenants and projects."""
        result = load_and_validate_config(config_repo)

        assert result.ica_config.default_nextflow_version == "25.10"
        assert len(result.ica_config.tenants) == 1

        tenant = result.ica_config.tenants[0]
        assert tenant.name == "umccr-prod"
        assert tenant.id == "1555b441-c3be-40b0-a8f0-fb9dc7500545"
        assert len(tenant.projects) == 1

        project = tenant.projects[0]
        assert project.id == "ea19a3f5-ec7c-4940-a474-c31cd91dbad4"
        assert project.name == "development"
        assert project.contexts == ["development"]
        assert len(project.oidc_auth) == 1
        assert project.oidc_auth[0].aws_role_arn == "arn:aws:iam::123456789012:role/test"

    def test_parses_pipelines(self, config_repo):
        """Pipelines are correctly parsed into dataclasses."""
        result = load_and_validate_config(config_repo)

        assert len(result.pipelines) == 1
        pipeline = result.pipelines[0]
        assert pipeline.workflow_name == "oncoanalyser"
        assert pipeline.workflow_version == "2.2.0"
        assert pipeline.git_commit_id == "b94cbc7"
        assert pipeline.pipeline_id == "abc-123"
        assert pipeline.release_status == "DRAFT"
        assert pipeline.tenants == ["umccr-prod"]
        assert pipeline.contexts == ["development"]
        assert pipeline.patch_files == []
        assert pipeline.ica_nextflow_version == "25.10"

    def test_missing_patches_yaml_returns_empty_list(self, config_repo):
        """When patches.yaml doesn't exist, patches list is empty."""
        result = load_and_validate_config(config_repo)
        assert result.patches == []

    def test_patches_yaml_loaded_when_present(self, config_repo):
        """When patches.yaml exists, patches are parsed correctly."""
        # Create the patch file so validation passes
        patches_dir = config_repo / "patches"
        patches_dir.mkdir(exist_ok=True)
        (patches_dir / "abc123.txt").write_text("patch content")

        patches_file = config_repo / "config" / "patches.yaml"
        patches_file.write_text(
            "patches:\n"
            "  - name: fix-memory\n"
            "    path: patches/abc123.txt\n"
            "    md5sum: abc123\n"
            "    description: Fix memory issue\n"
        )

        result = load_and_validate_config(config_repo)
        assert len(result.patches) == 1
        patch = result.patches[0]
        assert patch.name == "fix-memory"
        assert patch.path == "patches/abc123.txt"
        assert patch.md5sum == "abc123"
        assert patch.description == "Fix memory issue"

    def test_empty_pipelines_file(self, tmp_path):
        """Handles ica_pipelines.yaml with no pipelines entry."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "workflows.yaml").write_text("workflows: []\n")
        (config_dir / "contexts.yaml").write_text("contexts: []\n")
        (config_dir / "ica_config.yaml").write_text(
            "tenants: []\ndefault_nextflow_version: '25.10'\n"
        )
        # ica_pipelines.yaml with commented-out content (returns None from YAML parse)
        (config_dir / "ica_pipelines.yaml").write_text(
            "# No pipelines yet\n"
        )

        result = load_and_validate_config(tmp_path)
        assert result.pipelines == []

    def test_workflow_version_with_ica_nextflow_version(self, tmp_path):
        """WorkflowVersion ica_nextflow_version field is parsed when present."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "workflows.yaml").write_text(
            "workflows:\n"
            "  - name: test-wf\n"
            "    repo_uri: https://example.com/repo\n"
            "    versions:\n"
            "      - tag: '1.0.0'\n"
            "        git_commit_id: abcdef1\n"
            "        contexts:\n"
            "          - dev\n"
            "        ica_nextflow_version: '24.04'\n"
        )
        (config_dir / "contexts.yaml").write_text(
            "contexts:\n"
            "  - name: dev\n"
            "    description: Development\n"
        )
        (config_dir / "ica_config.yaml").write_text(
            "tenants: []\ndefault_nextflow_version: '25.10'\n"
        )
        (config_dir / "ica_pipelines.yaml").write_text("pipelines: []\n")

        result = load_and_validate_config(tmp_path)
        assert result.workflows[0].versions[0].ica_nextflow_version == "24.04"

    def test_raises_system_exit_for_missing_required_file(self, tmp_path):
        """Raises SystemExit when a required config file is missing."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "workflows.yaml").write_text("workflows: []\n")
        # Missing contexts.yaml

        with pytest.raises(SystemExit) as exc_info:
            load_and_validate_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "FILE NOT FOUND" in error_msg

    def test_multiple_tenants_and_projects(self, tmp_path):
        """Handles multiple tenants with multiple projects each."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "workflows.yaml").write_text("workflows: []\n")
        (config_dir / "contexts.yaml").write_text(
            "contexts:\n"
            "  - name: dev\n"
            "    description: Development\n"
            "  - name: prod\n"
            "    description: Production\n"
        )
        (config_dir / "ica_config.yaml").write_text(
            "tenants:\n"
            "  - name: tenant-a\n"
            "    id: id-a\n"
            "    projects:\n"
            "      - id: proj-1\n"
            "        name: project-one\n"
            "        oidc_auth:\n"
            "          - aws_role_arn: arn:1\n"
            "            secret_arn: arn:s1\n"
            "        contexts:\n"
            "          - dev\n"
            "      - id: proj-2\n"
            "        name: project-two\n"
            "        oidc_auth:\n"
            "          - aws_role_arn: arn:2\n"
            "            secret_arn: arn:s2\n"
            "        contexts:\n"
            "          - prod\n"
            "  - name: tenant-b\n"
            "    id: id-b\n"
            "    projects: []\n"
            "default_nextflow_version: '25.10'\n"
        )
        (config_dir / "ica_pipelines.yaml").write_text("pipelines: []\n")

        result = load_and_validate_config(tmp_path)
        assert len(result.ica_config.tenants) == 2
        assert len(result.ica_config.tenants[0].projects) == 2
        assert len(result.ica_config.tenants[1].projects) == 0
