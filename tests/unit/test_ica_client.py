"""Unit tests for the ICA client module.

Tests mock boto3 and wrapica calls since these external services
are not available in the test environment.
"""

import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nf_ica_cli.ica_client import (
    DeploymentTarget,
    _zip_source_directory,
    authenticate_oidc,
    create_pipeline,
    find_existing_pipeline,
    update_existing_pipeline,
)


class TestDeploymentTarget:
    """Tests for the DeploymentTarget dataclass."""

    def test_creates_deployment_target(self):
        """DeploymentTarget holds all required fields."""
        target = DeploymentTarget(
            project_id="proj-123",
            project_name="My Project",
            tenant_name="my-tenant",
            aws_role_arn="arn:aws:iam::123456789:role/my-role",
            secret_arn="arn:aws:secretsmanager:us-east-1:123456789:secret/ica-jwt",
        )

        assert target.project_id == "proj-123"
        assert target.project_name == "My Project"
        assert target.tenant_name == "my-tenant"
        assert target.aws_role_arn == "arn:aws:iam::123456789:role/my-role"
        assert target.secret_arn == "arn:aws:secretsmanager:us-east-1:123456789:secret/ica-jwt"

    def test_deployment_target_equality(self):
        """Two DeploymentTargets with same fields are equal."""
        target1 = DeploymentTarget(
            project_id="proj-123",
            project_name="My Project",
            tenant_name="tenant",
            aws_role_arn="arn:role",
            secret_arn="arn:secret",
        )
        target2 = DeploymentTarget(
            project_id="proj-123",
            project_name="My Project",
            tenant_name="tenant",
            aws_role_arn="arn:role",
            secret_arn="arn:secret",
        )

        assert target1 == target2


class TestAuthenticateOidc:
    """Tests for authenticate_oidc function."""

    @patch.dict(os.environ, {
        "AWS_WEB_IDENTITY_TOKEN_FILE": "/tmp/test_token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "",
    }, clear=False)
    @patch("nf_ica_cli.ica_client.boto3.client")
    @patch("builtins.open")
    def test_authenticates_via_web_identity_file(self, mock_open, mock_boto_client):
        """Authenticates using AWS_WEB_IDENTITY_TOKEN_FILE."""
        # Mock reading the token file
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "my-oidc-token\n"
        mock_open.return_value.strip = lambda: "my-oidc-token"

        # Mock STS client
        mock_sts = MagicMock()
        mock_sts.assume_role_with_web_identity.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEST",
                "SecretAccessKey": "secret_test",
                "SessionToken": "session_test",
            }
        }

        # Mock Secrets Manager client
        mock_secrets = MagicMock()
        mock_secrets.get_secret_value.return_value = {
            "SecretString": "ica-jwt-token-123"
        }

        # boto3.client returns different clients based on service name
        def client_factory(service_name, **kwargs):
            if service_name == "sts":
                return mock_sts
            elif service_name == "secretsmanager":
                return mock_secrets
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        result = authenticate_oidc(
            aws_role_arn="arn:aws:iam::123:role/deploy",
            secret_arn="arn:aws:secretsmanager:us-east-1:123:secret/jwt",
        )

        assert result == "ica-jwt-token-123"
        assert os.environ.get("ICAV2_ACCESS_TOKEN") == "ica-jwt-token-123"

        # Verify STS was called with correct args
        mock_sts.assume_role_with_web_identity.assert_called_once_with(
            RoleArn="arn:aws:iam::123:role/deploy",
            RoleSessionName="nf-ica-cli-deployment",
            WebIdentityToken="my-oidc-token",
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_when_no_oidc_token_available(self):
        """Raises RuntimeError when OIDC token is not available."""
        # Clear environment variables
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
        os.environ.pop("AWS_WEB_IDENTITY_TOKEN_FILE", None)

        with pytest.raises(RuntimeError, match="OIDC token not available"):
            authenticate_oidc(
                aws_role_arn="arn:aws:iam::123:role/deploy",
                secret_arn="arn:aws:secretsmanager:us-east-1:123:secret/jwt",
            )

    @patch.dict(os.environ, {
        "AWS_WEB_IDENTITY_TOKEN_FILE": "/tmp/test_token",
    }, clear=False)
    @patch("nf_ica_cli.ica_client.boto3.client")
    @patch("builtins.open")
    def test_raises_on_sts_failure(self, mock_open, mock_boto_client):
        """Raises RuntimeError when STS assume role fails."""
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "token\n"
        mock_open.return_value.strip = lambda: "token"

        mock_sts = MagicMock()
        mock_sts.assume_role_with_web_identity.side_effect = Exception("Access denied")
        mock_boto_client.return_value = mock_sts

        with pytest.raises(RuntimeError, match="Failed to assume AWS role"):
            authenticate_oidc(
                aws_role_arn="arn:aws:iam::123:role/deploy",
                secret_arn="arn:secret",
            )

    @patch.dict(os.environ, {
        "AWS_WEB_IDENTITY_TOKEN_FILE": "/tmp/test_token",
    }, clear=False)
    @patch("nf_ica_cli.ica_client.boto3.client")
    @patch("builtins.open")
    def test_raises_on_secret_retrieval_failure(self, mock_open, mock_boto_client):
        """Raises RuntimeError when secret retrieval fails."""
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "token\n"
        mock_open.return_value.strip = lambda: "token"

        mock_sts = MagicMock()
        mock_sts.assume_role_with_web_identity.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA",
                "SecretAccessKey": "secret",
                "SessionToken": "session",
            }
        }

        mock_secrets = MagicMock()
        mock_secrets.get_secret_value.side_effect = Exception("Secret not found")

        def client_factory(service_name, **kwargs):
            if service_name == "sts":
                return mock_sts
            elif service_name == "secretsmanager":
                return mock_secrets
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        with pytest.raises(RuntimeError, match="Failed to retrieve ICA JWT"):
            authenticate_oidc(
                aws_role_arn="arn:aws:iam::123:role/deploy",
                secret_arn="arn:secret",
            )


class TestCreatePipeline:
    """Tests for create_pipeline function."""

    @patch("nf_ica_cli.ica_client.create_nextflow_pipeline_from_zip")
    def test_creates_pipeline_successfully(self, mock_create, tmp_path):
        """Creates a pipeline and returns the pipeline ID."""
        # Set up source directory
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { }")

        # Mock wrapica response
        mock_pipeline = MagicMock()
        mock_pipeline.pipeline.id = "pipeline-uuid-123"
        mock_create.return_value = mock_pipeline

        result = create_pipeline(
            project_id="project-123",
            workflow_name="oncoanalyser",
            version="2.2.0",
            source_dir=source_dir,
            nextflow_version="22.10.0",
            description="Oncoanalyser v2.2.0",
        )

        assert result == "pipeline-uuid-123"

        # Verify wrapica was called with correct arguments
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == "project-123"
        assert call_kwargs["pipeline_code"] == "oncoanalyser__2.2.0"
        assert call_kwargs["workflow_description"] == "Oncoanalyser v2.2.0"
        # Verify zip_path was passed (a Path object)
        assert "zip_path" in call_kwargs

    @patch("nf_ica_cli.ica_client.create_nextflow_pipeline_from_zip")
    def test_raises_on_api_failure(self, mock_create, tmp_path):
        """Raises RuntimeError when wrapica create fails."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { }")

        mock_create.side_effect = Exception("API error: 403 Forbidden")

        with pytest.raises(RuntimeError, match="Failed to create pipeline"):
            create_pipeline(
                project_id="project-123",
                workflow_name="oncoanalyser",
                version="2.2.0",
                source_dir=source_dir,
                nextflow_version="22.10.0",
                description="desc",
            )

    def test_raises_for_missing_source_dir(self, tmp_path):
        """Raises FileNotFoundError when source directory doesn't exist."""
        missing_dir = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError, match="not found"):
            create_pipeline(
                project_id="project-123",
                workflow_name="wf",
                version="1.0",
                source_dir=missing_dir,
                nextflow_version="22.10.0",
                description="desc",
            )


class TestUpdateExistingPipeline:
    """Tests for update_existing_pipeline function."""

    @patch("nf_ica_cli.ica_client.add_pipeline_file")
    @patch("nf_ica_cli.ica_client.get_project_pipeline_obj")
    def test_updates_pipeline_successfully(self, mock_get_obj, mock_add_file, tmp_path):
        """Updates an existing pipeline by adding files."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { }")

        mock_get_obj.return_value = MagicMock()

        update_existing_pipeline(
            project_id="project-123",
            pipeline_id="pipeline-456",
            source_dir=source_dir,
            nextflow_version="22.10.0",
            description="Updated pipeline",
        )

        mock_get_obj.assert_called_once_with(
            project_id="project-123",
            pipeline_id="pipeline-456",
        )
        mock_add_file.assert_called_once()
        call_kwargs = mock_add_file.call_args[1]
        assert call_kwargs["project_id"] == "project-123"
        assert call_kwargs["pipeline_id"] == "pipeline-456"

    @patch("nf_ica_cli.ica_client.get_project_pipeline_obj")
    def test_raises_on_api_failure(self, mock_get_obj, tmp_path):
        """Raises RuntimeError when wrapica update fails."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { }")

        mock_get_obj.side_effect = Exception("API error: 404 Not Found")

        with pytest.raises(RuntimeError, match="Failed to update pipeline"):
            update_existing_pipeline(
                project_id="project-123",
                pipeline_id="pipeline-456",
                source_dir=source_dir,
                nextflow_version="22.10.0",
                description="desc",
            )

    def test_raises_for_missing_source_dir(self, tmp_path):
        """Raises FileNotFoundError when source directory doesn't exist."""
        missing_dir = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError, match="not found"):
            update_existing_pipeline(
                project_id="project-123",
                pipeline_id="pipeline-456",
                source_dir=missing_dir,
                nextflow_version="22.10.0",
                description="desc",
            )


class TestFindExistingPipeline:
    """Tests for find_existing_pipeline function."""

    @patch("nf_ica_cli.ica_client.list_project_pipelines")
    def test_finds_existing_pipeline(self, mock_list):
        """Returns pipeline ID when matching pipeline exists."""
        # Create mock pipelines
        mock_pipeline = MagicMock()
        mock_pipeline.pipeline.code = "oncoanalyser__2.2.0"
        mock_pipeline.pipeline.id = "found-pipeline-id"

        other_pipeline = MagicMock()
        other_pipeline.pipeline.code = "other-workflow__1.0.0"
        other_pipeline.pipeline.id = "other-id"

        mock_list.return_value = [other_pipeline, mock_pipeline]

        result = find_existing_pipeline(
            project_id="project-123",
            workflow_name="oncoanalyser",
            version="2.2.0",
        )

        assert result == "found-pipeline-id"
        mock_list.assert_called_once_with(project_id="project-123")

    @patch("nf_ica_cli.ica_client.list_project_pipelines")
    def test_returns_none_when_not_found(self, mock_list):
        """Returns None when no matching pipeline exists."""
        mock_pipeline = MagicMock()
        mock_pipeline.pipeline.code = "other-workflow__1.0.0"
        mock_pipeline.pipeline.id = "other-id"

        mock_list.return_value = [mock_pipeline]

        result = find_existing_pipeline(
            project_id="project-123",
            workflow_name="oncoanalyser",
            version="2.2.0",
        )

        assert result is None

    @patch("nf_ica_cli.ica_client.list_project_pipelines")
    def test_returns_none_for_empty_project(self, mock_list):
        """Returns None when project has no pipelines."""
        mock_list.return_value = []

        result = find_existing_pipeline(
            project_id="project-123",
            workflow_name="oncoanalyser",
            version="2.2.0",
        )

        assert result is None

    @patch("nf_ica_cli.ica_client.list_project_pipelines")
    def test_raises_on_api_failure(self, mock_list):
        """Raises RuntimeError when API call fails."""
        mock_list.side_effect = Exception("Connection timeout")

        with pytest.raises(RuntimeError, match="Failed to search for existing pipeline"):
            find_existing_pipeline(
                project_id="project-123",
                workflow_name="oncoanalyser",
                version="2.2.0",
            )


class TestZipSourceDirectory:
    """Tests for _zip_source_directory helper function."""

    def test_creates_valid_zip_file(self, tmp_path):
        """Creates a zip file containing all source files."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { }")
        sub_dir = source_dir / "modules"
        sub_dir.mkdir()
        (sub_dir / "module.nf").write_text("process FOO { }")

        zip_path = _zip_source_directory(source_dir)

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        # Verify zip contents
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(zf.namelist())
            assert "main.nf" in names
            assert str(Path("modules/module.nf")) in names

        # Clean up
        zip_path.unlink()
        zip_path.parent.rmdir()

    def test_raises_for_missing_directory(self, tmp_path):
        """Raises FileNotFoundError for nonexistent directory."""
        missing = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError, match="not found"):
            _zip_source_directory(missing)

    def test_raises_for_file_path(self, tmp_path):
        """Raises FileNotFoundError when path is a file, not directory."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")

        with pytest.raises(FileNotFoundError, match="not a directory"):
            _zip_source_directory(file_path)

    def test_handles_empty_directory(self, tmp_path):
        """Creates a zip even for an empty directory."""
        source_dir = tmp_path / "empty"
        source_dir.mkdir()

        zip_path = _zip_source_directory(source_dir)

        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert len(zf.namelist()) == 0

        # Clean up
        zip_path.unlink()
        zip_path.parent.rmdir()
