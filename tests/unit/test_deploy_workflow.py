"""Unit tests for the gh-actions-deploy-workflow handler."""

from pathlib import Path
from unittest.mock import MagicMock, patch, call

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
from nf_ica_cli.handlers.deploy_workflow import handle_deploy_workflow
from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.release_page import DeploymentResult
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def _make_oidc_auth(
    aws_role_arn: str = "arn:aws:iam::123456789:role/test-role",
    secret_arn: str = "arn:aws:secretsmanager:us-east-1:123456789:secret:test-secret",
) -> OidcAuth:
    return OidcAuth(aws_role_arn=aws_role_arn, secret_arn=secret_arn)


def _make_project(
    project_id: str = "proj-uuid-1",
    name: str = "project-dev",
    contexts: list = None,
    oidc_auth: list = None,
) -> IcaProject:
    return IcaProject(
        id=project_id,
        name=name,
        oidc_auth=oidc_auth or [_make_oidc_auth()],
        contexts=contexts or ["development"],
    )


def _make_tenant(
    name: str = "umccr",
    tenant_id: str = "tenant-uuid-1",
    projects: list = None,
) -> Tenant:
    return Tenant(
        name=name,
        id=tenant_id,
        projects=projects or [_make_project()],
    )


def _make_workflow(
    name: str = "oncoanalyser",
    repo_uri: str = "https://github.com/umccr/oncoanalyser.git",
    versions: list = None,
) -> Workflow:
    return Workflow(
        name=name,
        repo_uri=repo_uri,
        versions=versions or [
            WorkflowVersion(
                tag="2.2.0",
                git_commit_id="abc1234def5678",
                contexts=["development"],
                ica_nextflow_version=None,
            )
        ],
    )


def _make_app_config(
    config_repo: Path,
    workflows: list = None,
    tenants: list = None,
    pipelines: list = None,
    patches: list = None,
    default_nf_version: str = "25.10",
) -> AppConfig:
    return AppConfig(
        config_repo=config_repo,
        workflows=workflows or [_make_workflow()],
        contexts=[Context(name="development", description="Dev env")],
        ica_config=IcaConfig(
            tenants=tenants or [_make_tenant()],
            default_nextflow_version=default_nf_version,
        ),
        pipelines=pipelines or [],
        patches=patches or [],
    )


def _make_args(
    workflow_name: str = "oncoanalyser",
    workflow_version: str = "2.2.0",
    annotated_tag_name: str = "oncoanalyser/2.2.0__20250715143022",
) -> dict:
    return {
        "--workflow-name": workflow_name,
        "--workflow-version": workflow_version,
        "--annotated-tag-name": annotated_tag_name,
        "gh-actions-deploy-workflow": True,
    }


def _setup_pipelines_yaml(config_repo: Path, pipelines_list: list = None) -> Path:
    """Create ica_pipelines.yaml with given entries."""
    config_dir = config_repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    pipelines_path = config_dir / "ica_pipelines.yaml"
    data = {"pipelines": pipelines_list or []}
    save_yaml(pipelines_path, data)
    return pipelines_path


TAG_MESSAGE = """\
git_commit_id: abc1234def5678
contexts:
- development
patch_names: []
release_status: DRAFT
workflow_version_description: Test deployment
"""


class TestHandleDeployWorkflow:
    """Tests for handle_deploy_workflow handler."""

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_successful_deployment_creates_new_pipeline(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Successful deployment creates a new pipeline and GitHub Release."""
        config_repo = tmp_path / "config_repo"
        pipelines_path = _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.return_value = "jwt-token"
        mock_create_pipeline.return_value = "new-pipeline-uuid"
        mock_create_zip.return_value = tmp_path / "output.zip"

        config = _make_app_config(config_repo)
        args = _make_args()

        handle_deploy_workflow(args, config, config_repo)

        # Verify the pipeline was created
        mock_create_pipeline.assert_called_once()
        call_kwargs = mock_create_pipeline.call_args
        assert call_kwargs[1]["project_id"] == "proj-uuid-1"
        assert call_kwargs[1]["workflow_name"] == "oncoanalyser"
        assert call_kwargs[1]["version"] == "2.2.0"

        # Verify GitHub release was created
        mock_create_release.assert_called_once()

        # Verify pipeline was recorded in ica_pipelines.yaml
        data = load_yaml(pipelines_path)
        assert len(data["pipelines"]) == 1
        assert data["pipelines"][0]["pipeline_id"] == "new-pipeline-uuid"
        assert data["pipelines"][0]["workflow_name"] == "oncoanalyser"

    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_tag_message_retrieval_fails(
        self, mock_get_tag_message, tmp_path
    ):
        """Exits with SystemExit when git tag message can't be retrieved."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.side_effect = RuntimeError("tag not found")

        config = _make_app_config(config_repo)
        args = _make_args()

        with pytest.raises(SystemExit, match="Failed to retrieve annotated tag"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_tag_message_invalid(self, mock_get_tag_message, tmp_path):
        """Exits with SystemExit when tag message fails to decode (Req 7.3)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = "invalid: yaml: content:"

        config = _make_app_config(config_repo)
        args = _make_args()

        with pytest.raises(SystemExit, match="TAG DECODE"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_workflow_not_found(self, mock_get_tag_message, tmp_path):
        """Exits when workflow name is not in config (Req 5.1)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE

        config = _make_app_config(config_repo)
        args = _make_args(workflow_name="nonexistent")

        with pytest.raises(SystemExit, match="not found"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_no_projects_match_contexts(
        self, mock_get_tag_message, tmp_path
    ):
        """Exits with SystemExit when no ICA projects match contexts (Req 5.3)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE

        # Projects have "production" context but tag has "development"
        project = _make_project(contexts=["production"])
        tenant = _make_tenant(projects=[project])
        config = _make_app_config(config_repo, tenants=[tenant])
        args = _make_args()

        with pytest.raises(SystemExit, match="No ICA projects match"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_skips_project_on_auth_failure_continues_others(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Skips project on auth failure but deploys to others (Req 5.5, 5.12)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None

        # First project auth fails, second succeeds
        mock_auth.side_effect = [
            RuntimeError("OIDC failed"),
            "jwt-token-2",
        ]
        mock_create_pipeline.return_value = "pipeline-uuid-2"
        mock_create_zip.return_value = tmp_path / "output.zip"

        project1 = _make_project(
            project_id="proj-1", name="project-fail", contexts=["development"]
        )
        project2 = _make_project(
            project_id="proj-2", name="project-success", contexts=["development"]
        )
        tenant = _make_tenant(projects=[project1, project2])
        config = _make_app_config(config_repo, tenants=[tenant])
        args = _make_args()

        # Partial failure should exit non-zero (Req 5.12)
        with pytest.raises(SystemExit) as exc_info:
            handle_deploy_workflow(args, config, config_repo)

        assert exc_info.value.code == 1

    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_all_deployments_fail_no_release(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        tmp_path,
    ):
        """No GitHub Release when all deployments fail (Req 5.15)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.side_effect = RuntimeError("OIDC failed")

        config = _make_app_config(config_repo)
        args = _make_args()

        with pytest.raises(SystemExit, match="All deployments failed"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_clone_fails(self, mock_get_tag_message, mock_clone, tmp_path):
        """Exits with SystemExit when repo clone fails (Req 5.6)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.side_effect = RuntimeError("clone failed")

        config = _make_app_config(config_repo)
        args = _make_args()

        with pytest.raises(SystemExit, match="Failed to clone"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.apply_patches")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_exits_when_patch_fails(
        self, mock_get_tag_message, mock_clone, mock_apply_patches, tmp_path
    ):
        """Exits with SystemExit when patch application fails (Req 5.8)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        tag_message_with_patches = """\
git_commit_id: abc1234def5678
contexts:
- development
patch_names:
- my-patch
release_status: DRAFT
workflow_version_description: ''
"""
        mock_get_tag_message.return_value = tag_message_with_patches
        mock_clone.return_value = None
        mock_apply_patches.side_effect = RuntimeError(
            "Error: [GIT] Failed to apply patch 'my-patch'"
        )

        config = _make_app_config(config_repo)
        args = _make_args()

        with pytest.raises(SystemExit, match="Failed to apply patch"):
            handle_deploy_workflow(args, config, config_repo)

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_records_pipeline_in_yaml(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Records pipeline entry in ica_pipelines.yaml after deployment (Req 5.10)."""
        config_repo = tmp_path / "config_repo"
        pipelines_path = _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.return_value = "jwt-token"
        mock_create_pipeline.return_value = "new-pipeline-uuid"
        mock_create_zip.return_value = tmp_path / "output.zip"

        config = _make_app_config(config_repo)
        args = _make_args()

        handle_deploy_workflow(args, config, config_repo)

        data = load_yaml(pipelines_path)
        entry = data["pipelines"][0]
        assert entry["workflow_name"] == "oncoanalyser"
        assert entry["workflow_version"] == "2.2.0"
        assert entry["git_commit_id"] == "abc1234def5678"
        assert entry["pipeline_id"] == "new-pipeline-uuid"
        assert entry["release_status"] == "DRAFT"
        assert entry["tenants"] == ["umccr"]
        assert entry["contexts"] == ["development"]
        assert entry["patch_files"] == []
        assert entry["ica_nextflow_version"] == "25.10"

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_uses_workflow_specific_nextflow_version(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Uses version-specific Nextflow version when available."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.return_value = "jwt-token"
        mock_create_pipeline.return_value = "pipeline-uuid"
        mock_create_zip.return_value = tmp_path / "output.zip"

        workflow = _make_workflow(
            versions=[
                WorkflowVersion(
                    tag="2.2.0",
                    git_commit_id="abc1234def5678",
                    contexts=["development"],
                    ica_nextflow_version="24.04",
                )
            ]
        )
        config = _make_app_config(config_repo, workflows=[workflow])
        args = _make_args()

        handle_deploy_workflow(args, config, config_repo)

        # Verify the version-specific NF version was used
        call_kwargs = mock_create_pipeline.call_args[1]
        assert call_kwargs["nextflow_version"] == "24.04"

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_multiple_projects_same_context(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Deploys to all projects matching the context (Req 5.2)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.return_value = "jwt-token"
        mock_create_pipeline.side_effect = ["pipeline-1", "pipeline-2"]
        mock_create_zip.return_value = tmp_path / "output.zip"

        project1 = _make_project(
            project_id="proj-1", name="project-1", contexts=["development"]
        )
        project2 = _make_project(
            project_id="proj-2", name="project-2", contexts=["development"]
        )
        tenant = _make_tenant(projects=[project1, project2])
        config = _make_app_config(config_repo, tenants=[tenant])
        args = _make_args()

        handle_deploy_workflow(args, config, config_repo)

        # Both projects should get deployments
        assert mock_create_pipeline.call_count == 2

        # Both should be in the release
        mock_create_release.assert_called_once()

    @patch("nf_ica_cli.handlers.deploy_workflow.create_github_release")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline_zip")
    @patch("nf_ica_cli.handlers.deploy_workflow.create_pipeline")
    @patch("nf_ica_cli.handlers.deploy_workflow.authenticate_oidc")
    @patch("nf_ica_cli.handlers.deploy_workflow.clone_at_commit")
    @patch("nf_ica_cli.handlers.deploy_workflow.get_tag_message")
    def test_skips_project_without_oidc_auth(
        self,
        mock_get_tag_message,
        mock_clone,
        mock_auth,
        mock_create_pipeline,
        mock_create_zip,
        mock_create_release,
        tmp_path,
    ):
        """Skips project with no OIDC auth configured and deploys to others."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo)

        mock_get_tag_message.return_value = TAG_MESSAGE
        mock_clone.return_value = None
        mock_auth.return_value = "jwt-token"
        mock_create_pipeline.return_value = "pipeline-uuid"
        mock_create_zip.return_value = tmp_path / "output.zip"

        # First project has no OIDC auth
        project_no_auth = IcaProject(
            id="proj-no-auth",
            name="no-auth-project",
            oidc_auth=[],
            contexts=["development"],
        )
        project_with_auth = _make_project(
            project_id="proj-ok", name="good-project", contexts=["development"]
        )
        tenant = _make_tenant(projects=[project_no_auth, project_with_auth])
        config = _make_app_config(config_repo, tenants=[tenant])
        args = _make_args()

        # Partial failure exits non-zero
        with pytest.raises(SystemExit) as exc_info:
            handle_deploy_workflow(args, config, config_repo)
        assert exc_info.value.code == 1
