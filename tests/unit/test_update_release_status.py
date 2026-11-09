"""Unit tests for the update-workflow-version-release-status handler.

The handler operates in two mutually exclusive modes:

* publish (--release-status RELEASED): verify the deployed ICA pipeline matches
  the configured source commit + patches, release it, flip the YAML to
  RELEASED, and publish the GitHub release.
* amend (--git-commit-id / --add-patch / --remove-patch): rebuild the pipeline
  source, replace the ICA asset, update ica_pipelines.yaml (and workflows.yaml
  for a commit change), and refresh the GitHub release. Stays DRAFT.

ICA/GitHub side effects are mocked. The handler module path is used for all
patch targets so the real network/CLI is never touched.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

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
)
from nf_ica_cli.handlers.update_release_status import handle_update_release_status
from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.yaml_io import load_yaml, save_yaml

HANDLER = "nf_ica_cli.handlers.update_release_status"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _make_pipeline_entry(
    workflow_name="sash",
    workflow_version="0.6.5-rc__20261028055117",
    git_commit_id="3b9fb48",
    release_status="DRAFT",
    patch_files=None,
) -> PipelineEntry:
    return PipelineEntry(
        workflow_name=workflow_name,
        workflow_version=workflow_version,
        git_commit_id=git_commit_id,
        pipeline_id="b4ef2744-pipeline",
        release_status=release_status,
        tenants=["umccr-prod"],
        contexts=["development"],
        patch_files=patch_files if patch_files is not None else ["standard_icav2_config"],
        ica_nextflow_version="25.10.2",
    )


def _make_ica_config() -> IcaConfig:
    project = IcaProject(
        id="ea19a3f5-project",
        name="development",
        oidc_auth=[OidcAuth(aws_role_arn="arn:role", secret_arn="arn:secret")],
        contexts=["development"],
    )
    tenant = Tenant(name="umccr-prod", id="tenant-uuid", projects=[project])
    return IcaConfig(tenants=[tenant], default_nextflow_version="25.10")


def _make_workflow() -> Workflow:
    return Workflow(
        name="sash",
        repo_uri="https://github.com/umccr/sash",
        versions=[
            WorkflowVersion(
                tag="0.6.5-rc",
                git_commit_id="3b9fb48",
                contexts=["development"],
                ica_nextflow_version="25.10.2",
            )
        ],
    )


def _make_patches() -> list:
    return [
        PatchEntry(
            name="standard_icav2_config",
            path="patches/std.txt",
            md5sum="std",
            description="Standard config",
        ),
        PatchEntry(
            name="extra-patch",
            path="patches/extra.txt",
            md5sum="extra",
            description="Extra patch",
        ),
    ]


def _make_app_config(config_repo, pipelines=None, patches=None) -> AppConfig:
    return AppConfig(
        config_repo=config_repo,
        workflows=[_make_workflow()],
        contexts=[Context(name="development", description="dev")],
        ica_config=_make_ica_config(),
        pipelines=pipelines if pipelines is not None else [_make_pipeline_entry()],
        patches=patches if patches is not None else _make_patches(),
    )


def _make_args(
    workflow_name="sash",
    version_tag="0.6.5-rc__20261028055117",
    release_status=None,
    git_commit_id=None,
    add_patch=None,
    remove_patch=None,
) -> dict:
    return {
        "--workflow-name": workflow_name,
        "--workflow-version-tag": version_tag,
        "--release-status": release_status,
        "--git-commit-id": git_commit_id,
        "--add-patch": add_patch or [],
        "--remove-patch": remove_patch or [],
        "update-workflow-version-release-status": True,
    }


def _setup_repo(config_repo: Path, pipelines_list: list, patch_files=None) -> None:
    """Create config/ica_pipelines.yaml, config/workflows.yaml and patch files."""
    config_dir = config_repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(config_dir / "ica_pipelines.yaml", {"pipelines": pipelines_list})
    save_yaml(
        config_dir / "workflows.yaml",
        {
            "workflows": [
                {
                    "name": "sash",
                    "repo_uri": "https://github.com/umccr/sash",
                    "versions": [
                        {
                            "tag": "0.6.5-rc",
                            "git_commit_id": "3b9fb48",
                            "contexts": ["development"],
                        }
                    ],
                }
            ]
        },
    )
    patches_dir = config_repo / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    for fname in patch_files or ["std.txt", "extra.txt"]:
        (patches_dir / fname).write_text("patch content")


def _raw_pipeline(**overrides) -> dict:
    base = {
        "workflow_name": "sash",
        "workflow_version": "0.6.5-rc__20261028055117",
        "git_commit_id": "3b9fb48",
        "pipeline_id": "b4ef2744-pipeline",
        "release_status": "DRAFT",
        "tenants": ["umccr-prod"],
        "contexts": ["development"],
        "patch_files": ["standard_icav2_config"],
        "ica_nextflow_version": "25.10.2",
    }
    base.update(overrides)
    return base


@pytest.fixture
def ica_token(monkeypatch):
    monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "test-token")


# ---------------------------------------------------------------------------
# Mode selection / validation
# ---------------------------------------------------------------------------


class TestModeValidation:
    def test_requires_a_mode(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args()  # nothing set

        with pytest.raises(SystemExit, match="Nothing to do"):
            handle_update_release_status(args, config, config_repo)

    def test_release_status_and_edit_are_mutually_exclusive(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(release_status="RELEASED", add_patch=["extra-patch"])

        with pytest.raises(SystemExit, match="mutually exclusive"):
            handle_update_release_status(args, config, config_repo)

    def test_pipeline_not_found(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [])
        config = _make_app_config(config_repo, pipelines=[])
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="No pipeline entry found"):
            handle_update_release_status(args, config, config_repo)

    def test_already_released_cannot_be_modified(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline(release_status="RELEASED")])
        config = _make_app_config(
            config_repo, pipelines=[_make_pipeline_entry(release_status="RELEASED")]
        )
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="already RELEASED"):
            handle_update_release_status(args, config, config_repo)

    def test_release_status_must_be_released(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(release_status="DRAFT")

        with pytest.raises(SystemExit, match="may only be set to RELEASED"):
            handle_update_release_status(args, config, config_repo)

    def test_requires_ica_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ICAV2_ACCESS_TOKEN", raising=False)
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="ICAV2_ACCESS_TOKEN"):
            handle_update_release_status(args, config, config_repo)


# ---------------------------------------------------------------------------
# Mode A: publish
# ---------------------------------------------------------------------------


class TestRelease:
    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.release_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="https://github.com/umccr/nf-ica/blob/sha")
    @patch(f"{HANDLER}.generate_diffs", return_value=[])
    @patch(f"{HANDLER}.export_pipeline_source")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_releases_when_pipeline_matches(
        self,
        mock_clone,
        mock_apply,
        mock_export,
        mock_diffs,
        mock_baseurl,
        mock_release,
        mock_update_release,
        tmp_path,
        ica_token,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(release_status="RELEASED")

        handle_update_release_status(args, config, config_repo)

        # ICA pipeline released, YAML flipped, GitHub release published.
        mock_release.assert_called_once_with(
            project_id="ea19a3f5-project", pipeline_id="b4ef2744-pipeline"
        )
        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        assert data["pipelines"][0]["release_status"] == "RELEASED"
        mock_update_release.assert_called_once()
        kwargs = mock_update_release.call_args.kwargs
        assert kwargs["tag_name"] == "sash/0.6.5-rc__20261028055117"
        assert kwargs["publish"] is True

    @patch(f"{HANDLER}.release_pipeline")
    @patch(f"{HANDLER}.generate_diffs")
    @patch(f"{HANDLER}.export_pipeline_source")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_refuses_release_when_pipeline_diverges(
        self,
        mock_clone,
        mock_apply,
        mock_export,
        mock_diffs,
        mock_release,
        tmp_path,
        ica_token,
    ):
        from nf_ica_cli.diff_generator import FileDiff

        mock_diffs.return_value = [
            FileDiff(
                relative_path="main.nf",
                diff_content="diff",
                is_new_file=False,
                is_deleted=False,
            )
        ]
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="does not match"):
            handle_update_release_status(args, config, config_repo)

        mock_release.assert_not_called()
        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        assert data["pipelines"][0]["release_status"] == "DRAFT"

    def test_release_fails_when_patch_unregistered(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline(patch_files=["ghost"])])
        config = _make_app_config(
            config_repo,
            pipelines=[_make_pipeline_entry(patch_files=["ghost"])],
        )
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="not .*registered"):
            handle_update_release_status(args, config, config_repo)


# ---------------------------------------------------------------------------
# Mode B: amend
# ---------------------------------------------------------------------------


class TestAmend:
    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="https://github.com/umccr/nf-ica/blob/sha")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_add_patch_updates_yaml_and_ica_and_release(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(add_patch=["extra-patch"])

        handle_update_release_status(args, config, config_repo)

        # patch_files updated in ica_pipelines.yaml, entry stays DRAFT.
        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        entry = data["pipelines"][0]
        assert entry["patch_files"] == ["standard_icav2_config", "extra-patch"]
        assert entry["release_status"] == "DRAFT"

        mock_update_pipeline.assert_called_once()
        # Release notes refreshed, asset re-uploaded, not published.
        kwargs = mock_update_release.call_args.kwargs
        assert kwargs["publish"] is False
        assert len(kwargs["artefact_paths"]) == 1

    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="https://x/blob/sha")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_remove_patch(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(remove_patch=["standard_icav2_config"])

        handle_update_release_status(args, config, config_repo)

        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        assert data["pipelines"][0]["patch_files"] == []

    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_git_commit_updates_both_yaml_files(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(git_commit_id="abcdef1")

        handle_update_release_status(args, config, config_repo)

        pipelines = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        assert pipelines["pipelines"][0]["git_commit_id"] == "abcdef1"

        workflows = load_yaml(config_repo / "config" / "workflows.yaml")
        ver = workflows["workflows"][0]["versions"][0]
        assert ver["tag"] == "0.6.5-rc"
        assert ver["git_commit_id"] == "abcdef1"

        # Clone uses the new commit.
        assert mock_clone.call_args.args[1] == "abcdef1"

    def test_add_unregistered_patch_fails(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(add_patch=["ghost-patch"])

        with pytest.raises(SystemExit, match="not registered"):
            handle_update_release_status(args, config, config_repo)

    def test_invalid_git_commit_fails(self, tmp_path, ica_token):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(git_commit_id="ZZZ")

        with pytest.raises(SystemExit, match="Invalid git commit"):
            handle_update_release_status(args, config, config_repo)

    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_duplicate_add_is_noop_info(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
        capsys,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(add_patch=["standard_icav2_config"])

        handle_update_release_status(args, config, config_repo)

        out = capsys.readouterr().out
        assert "already applied" in out
        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        # Unchanged — still a single copy.
        assert data["pipelines"][0]["patch_files"] == ["standard_icav2_config"]

    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_remove_absent_patch_is_noop_info(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
        capsys,
    ):
        config_repo = tmp_path / "repo"
        _setup_repo(config_repo, [_raw_pipeline()])
        config = _make_app_config(config_repo)
        args = _make_args(remove_patch=["extra-patch"])

        handle_update_release_status(args, config, config_repo)

        out = capsys.readouterr().out
        assert "nothing to remove" in out
        data = load_yaml(config_repo / "config" / "ica_pipelines.yaml")
        assert data["pipelines"][0]["patch_files"] == ["standard_icav2_config"]

    @patch(f"{HANDLER}.update_github_release")
    @patch(f"{HANDLER}.create_pipeline_zip")
    @patch(f"{HANDLER}.update_pipeline")
    @patch(f"{HANDLER}.get_github_blob_base_url", return_value="")
    @patch(f"{HANDLER}.apply_patches")
    @patch(f"{HANDLER}.clone_at_commit")
    def test_preserves_yaml_comments(
        self,
        mock_clone,
        mock_apply,
        mock_baseurl,
        mock_update_pipeline,
        mock_zip,
        mock_update_release,
        tmp_path,
        ica_token,
    ):
        config_repo = tmp_path / "repo"
        config_dir = config_repo / "config"
        config_dir.mkdir(parents=True)
        (config_repo / "patches").mkdir(parents=True)
        (config_repo / "patches" / "std.txt").write_text("x")
        (config_repo / "patches" / "extra.txt").write_text("x")
        (config_dir / "workflows.yaml").write_text(
            "workflows:\n"
            "  - name: sash\n"
            "    repo_uri: https://github.com/umccr/sash\n"
            "    versions:\n"
            "      - tag: 0.6.5-rc\n"
            "        git_commit_id: 3b9fb48\n"
            "        contexts:\n"
            "          - development\n"
        )
        (config_dir / "ica_pipelines.yaml").write_text(
            "# tracking file\n"
            "pipelines:\n"
            "  - workflow_name: sash\n"
            "    workflow_version: 0.6.5-rc__20261028055117\n"
            "    git_commit_id: 3b9fb48\n"
            "    pipeline_id: b4ef2744-pipeline\n"
            "    release_status: DRAFT\n"
            "    tenants:\n"
            "      - umccr-prod\n"
            "    contexts:\n"
            "      - development\n"
            "    patch_files:\n"
            "      - standard_icav2_config\n"
            "    ica_nextflow_version: 25.10.2\n"
        )
        config = _make_app_config(config_repo)
        args = _make_args(add_patch=["extra-patch"])

        handle_update_release_status(args, config, config_repo)

        raw = (config_dir / "ica_pipelines.yaml").read_text()
        assert "# tracking file" in raw
        assert "extra-patch" in raw
