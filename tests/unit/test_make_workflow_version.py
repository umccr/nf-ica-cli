"""Unit tests for the make-workflow-version handler.

Tests cover:
- Successful tag creation with all valid inputs
- Release status validation failure
- Context validation failure
- Workflow not found in workflows.yaml
- Version tag not registered for workflow
- Patch name not registered
- Tag already exists
- Git operation failure during tag creation
- Empty patch list (valid case)
- Optional description (empty string when not provided)
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nf_ica_cli.config import AppConfig, Workflow, WorkflowVersion, Context, IcaConfig, PipelineEntry
from nf_ica_cli.handlers.make_workflow_version import handle_make_workflow_version
from nf_ica_cli.patches import PatchEntry


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample AppConfig for testing."""
    return AppConfig(
        config_repo=tmp_path,
        workflows=[
            Workflow(
                name="oncoanalyser",
                repo_uri="https://github.com/umccr/oncoanalyser.git",
                versions=[
                    WorkflowVersion(
                        tag="2.2.0",
                        git_commit_id="abc1234",
                        contexts=["production", "development"],
                        ica_nextflow_version="23.10.0",
                    ),
                    WorkflowVersion(
                        tag="2.3.0",
                        git_commit_id="def5678",
                        contexts=["development"],
                    ),
                ],
            ),
        ],
        contexts=[
            Context(name="production", description="Production environment"),
            Context(name="development", description="Development environment"),
        ],
        ica_config=IcaConfig(tenants=[], default_nextflow_version="23.10.0"),
        pipelines=[],
        patches=[
            PatchEntry(
                name="fix-memory",
                path="patches/abc123.txt",
                md5sum="abc123",
                description="Fix memory allocation",
            ),
            PatchEntry(
                name="add-retry",
                path="patches/def456.txt",
                md5sum="def456",
                description="Add retry logic",
            ),
        ],
    )


def _make_args(
    workflow_name="oncoanalyser",
    version_tag="2.2.0",
    git_commit_id="abc1234",
    contexts=None,
    patch_names=None,
    release_status="DRAFT",
    description=None,
):
    """Helper to build a docopt-like args dict."""
    return {
        "--workflow-name": workflow_name,
        "--workflow-version-tag": version_tag,
        "--workflow-version-git-commit-id": git_commit_id,
        "--workflow-version-context": contexts or ["production"],
        "--workflow-patch-name": patch_names or [],
        "--release-status": release_status,
        "--workflow-version-description": description,
    }


class TestMakeWorkflowVersionSuccess:
    """Tests for successful tag creation."""

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_all_valid_inputs(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(patch_names=["fix-memory"])

        handle_make_workflow_version(args, sample_config, tmp_path)

        mock_make_tag.assert_called_once_with("oncoanalyser", "2.2.0")
        mock_tag_exists.assert_called_once_with(tmp_path, "oncoanalyser/2.2.0__20250715143022")
        mock_create_tag.assert_called_once()
        call_args = mock_create_tag.call_args
        assert call_args[0][0] == tmp_path
        assert call_args[0][1] == "oncoanalyser/2.2.0__20250715143022"
        # Verify the tag message contains expected content
        tag_message = call_args[0][2]
        assert "abc1234" in tag_message
        assert "production" in tag_message
        assert "fix-memory" in tag_message
        assert "DRAFT" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_empty_patch_list(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(patch_names=[])

        handle_make_workflow_version(args, sample_config, tmp_path)

        mock_create_tag.assert_called_once()
        tag_message = mock_create_tag.call_args[0][2]
        assert "patch_names" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_description(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(description="New release with bugfixes")

        handle_make_workflow_version(args, sample_config, tmp_path)

        tag_message = mock_create_tag.call_args[0][2]
        assert "New release with bugfixes" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_multiple_contexts(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(contexts=["production", "development"])

        handle_make_workflow_version(args, sample_config, tmp_path)

        tag_message = mock_create_tag.call_args[0][2]
        assert "production" in tag_message
        assert "development" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_multiple_patches(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(patch_names=["fix-memory", "add-retry"])

        handle_make_workflow_version(args, sample_config, tmp_path)

        tag_message = mock_create_tag.call_args[0][2]
        assert "fix-memory" in tag_message
        assert "add-retry" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_creates_tag_with_released_status(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(release_status="RELEASED")

        handle_make_workflow_version(args, sample_config, tmp_path)

        tag_message = mock_create_tag.call_args[0][2]
        assert "RELEASED" in tag_message


class TestMakeWorkflowVersionValidation:
    """Tests for validation failures before tag creation."""

    def test_invalid_release_status_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(release_status="INVALID")

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "VALIDATION" in error_msg
        assert "INVALID" in error_msg

    def test_invalid_context_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(contexts=["staging"])

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "VALIDATION" in error_msg
        assert "staging" in error_msg

    def test_second_invalid_context_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(contexts=["production", "nonexistent"])

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "nonexistent" in error_msg

    def test_workflow_not_found_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(workflow_name="unknown-workflow")

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "VALIDATION" in error_msg
        assert "unknown-workflow" in error_msg
        assert "not found" in error_msg

    def test_version_not_registered_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(version_tag="9.9.9")

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "VALIDATION" in error_msg
        assert "9.9.9" in error_msg
        assert "not registered" in error_msg

    def test_unregistered_patch_raises_system_exit(self, sample_config, tmp_path):
        args = _make_args(patch_names=["nonexistent-patch"])

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "VALIDATION" in error_msg
        assert "nonexistent-patch" in error_msg
        assert "not registered" in error_msg

    def test_unregistered_patch_lists_available_patches(self, sample_config, tmp_path):
        args = _make_args(patch_names=["nonexistent-patch"])

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "fix-memory" in error_msg
        assert "add-retry" in error_msg

    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=True)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_existing_tag_raises_system_exit(
        self, mock_make_tag, mock_tag_exists, sample_config, tmp_path
    ):
        args = _make_args()

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "GIT" in error_msg
        assert "already exists" in error_msg
        assert "oncoanalyser/2.2.0__20250715143022" in error_msg

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag", side_effect=RuntimeError("git tag failed"))
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_git_failure_raises_system_exit(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args()

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, sample_config, tmp_path)

        error_msg = str(exc_info.value)
        assert "GIT" in error_msg
        assert "Failed to create annotated tag" in error_msg


class TestMakeWorkflowVersionValidationOrder:
    """Tests to verify all validation happens BEFORE tag creation (Req 3.3)."""

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists")
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name")
    def test_invalid_release_status_does_not_call_git(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(release_status="INVALID")

        with pytest.raises(SystemExit):
            handle_make_workflow_version(args, sample_config, tmp_path)

        mock_make_tag.assert_not_called()
        mock_tag_exists.assert_not_called()
        mock_create_tag.assert_not_called()

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists")
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name")
    def test_invalid_context_does_not_call_git(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(contexts=["invalid-ctx"])

        with pytest.raises(SystemExit):
            handle_make_workflow_version(args, sample_config, tmp_path)

        mock_make_tag.assert_not_called()
        mock_tag_exists.assert_not_called()
        mock_create_tag.assert_not_called()

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists")
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name")
    def test_unregistered_version_does_not_call_git(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(version_tag="9.9.9")

        with pytest.raises(SystemExit):
            handle_make_workflow_version(args, sample_config, tmp_path)

        mock_make_tag.assert_not_called()
        mock_tag_exists.assert_not_called()
        mock_create_tag.assert_not_called()

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists")
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name")
    def test_unregistered_patch_does_not_call_git(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        args = _make_args(patch_names=["nonexistent"])

        with pytest.raises(SystemExit):
            handle_make_workflow_version(args, sample_config, tmp_path)

        mock_make_tag.assert_not_called()
        mock_tag_exists.assert_not_called()
        mock_create_tag.assert_not_called()


class TestMakeWorkflowVersionEdgeCases:
    """Tests for edge cases."""

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_none_patch_names_treated_as_empty(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        """When docopt returns None for --workflow-patch-name, treat as empty list."""
        args = _make_args()
        args["--workflow-patch-name"] = None

        handle_make_workflow_version(args, sample_config, tmp_path)

        mock_create_tag.assert_called_once()
        tag_message = mock_create_tag.call_args[0][2]
        assert "patch_names" in tag_message

    @patch("nf_ica_cli.handlers.make_workflow_version.create_annotated_tag")
    @patch("nf_ica_cli.handlers.make_workflow_version.tag_exists", return_value=False)
    @patch("nf_ica_cli.handlers.make_workflow_version.make_tag_name", return_value="oncoanalyser/2.2.0__20250715143022")
    def test_none_description_treated_as_empty_string(
        self, mock_make_tag, mock_tag_exists, mock_create_tag, sample_config, tmp_path
    ):
        """When --workflow-version-description is None, use empty string."""
        args = _make_args(description=None)

        handle_make_workflow_version(args, sample_config, tmp_path)

        mock_create_tag.assert_called_once()
        tag_message = mock_create_tag.call_args[0][2]
        assert "workflow_version_description" in tag_message

    def test_empty_patches_registry_reports_none_available(self, tmp_path):
        """When no patches are registered, error message says '(none)'."""
        config = AppConfig(
            config_repo=tmp_path,
            workflows=[
                Workflow(
                    name="oncoanalyser",
                    repo_uri="https://github.com/umccr/oncoanalyser.git",
                    versions=[
                        WorkflowVersion(
                            tag="2.2.0",
                            git_commit_id="abc1234",
                            contexts=["production"],
                        ),
                    ],
                ),
            ],
            contexts=[Context(name="production", description="Prod")],
            ica_config=IcaConfig(tenants=[], default_nextflow_version="23.10.0"),
            pipelines=[],
            patches=[],
        )
        args = _make_args(patch_names=["some-patch"])

        with pytest.raises(SystemExit) as exc_info:
            handle_make_workflow_version(args, config, tmp_path)

        error_msg = str(exc_info.value)
        assert "(none)" in error_msg
