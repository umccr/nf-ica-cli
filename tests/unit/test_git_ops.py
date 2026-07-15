"""Unit tests for nf_ica_cli.git_ops module.

Tests mock subprocess.run to verify correct git commands are invoked
without requiring an actual git repository.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, call

import pytest

from nf_ica_cli.git_ops import (
    create_annotated_tag,
    tag_exists,
    clone_at_commit,
    get_tag_message,
)


@pytest.fixture
def mock_subprocess_run():
    """Fixture that patches subprocess.run."""
    with patch("nf_ica_cli.git_ops.subprocess.run") as mock_run:
        yield mock_run


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    """Helper to create a CompletedProcess object."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestCreateAnnotatedTag:
    """Tests for create_annotated_tag."""

    def test_creates_tag_with_correct_command(self, mock_subprocess_run):
        """Verify the correct git command is invoked."""
        mock_subprocess_run.return_value = _make_completed_process()
        repo_dir = Path("/tmp/my-repo")

        create_annotated_tag(repo_dir, "v1.0.0", "Release 1.0.0")

        mock_subprocess_run.assert_called_once_with(
            ["git", "tag", "-a", "v1.0.0", "-m", "Release 1.0.0"],
            cwd="/tmp/my-repo",
            capture_output=True,
            text=True,
        )

    def test_raises_runtime_error_on_failure(self, mock_subprocess_run):
        """Verify RuntimeError is raised when git exits non-zero."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=128,
            stderr="fatal: tag 'v1.0.0' already exists",
        )
        repo_dir = Path("/tmp/my-repo")

        with pytest.raises(RuntimeError, match="Failed to create annotated tag"):
            create_annotated_tag(repo_dir, "v1.0.0", "Release 1.0.0")

    def test_error_message_includes_details(self, mock_subprocess_run):
        """Verify error message includes command, exit code, and stderr."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=1,
            stderr="some error",
        )
        repo_dir = Path("/tmp/my-repo")

        with pytest.raises(RuntimeError) as exc_info:
            create_annotated_tag(repo_dir, "my-tag", "msg")

        error_msg = str(exc_info.value)
        assert "exited with code 1" in error_msg
        assert "some error" in error_msg
        assert "my-tag" in error_msg

    def test_multiline_message(self, mock_subprocess_run):
        """Verify multiline messages are passed correctly."""
        mock_subprocess_run.return_value = _make_completed_process()
        repo_dir = Path("/tmp/my-repo")
        message = "git_commit_id: abc1234\ncontexts:\n  - production"

        create_annotated_tag(repo_dir, "workflow/v1__202507", message)

        mock_subprocess_run.assert_called_once_with(
            ["git", "tag", "-a", "workflow/v1__202507", "-m", message],
            cwd="/tmp/my-repo",
            capture_output=True,
            text=True,
        )


class TestTagExists:
    """Tests for tag_exists."""

    def test_returns_true_when_tag_found(self, mock_subprocess_run):
        """Verify True is returned when git tag -l produces output."""
        mock_subprocess_run.return_value = _make_completed_process(
            stdout="v1.0.0\n",
        )
        repo_dir = Path("/tmp/my-repo")

        result = tag_exists(repo_dir, "v1.0.0")

        assert result is True
        mock_subprocess_run.assert_called_once_with(
            ["git", "tag", "-l", "v1.0.0"],
            cwd="/tmp/my-repo",
            capture_output=True,
            text=True,
        )

    def test_returns_false_when_tag_not_found(self, mock_subprocess_run):
        """Verify False is returned when git tag -l produces no output."""
        mock_subprocess_run.return_value = _make_completed_process(
            stdout="",
        )
        repo_dir = Path("/tmp/my-repo")

        result = tag_exists(repo_dir, "nonexistent")

        assert result is False

    def test_returns_false_for_whitespace_only_output(self, mock_subprocess_run):
        """Verify False is returned when output is only whitespace."""
        mock_subprocess_run.return_value = _make_completed_process(
            stdout="  \n",
        )
        repo_dir = Path("/tmp/my-repo")

        result = tag_exists(repo_dir, "nonexistent")

        assert result is False

    def test_raises_on_git_failure(self, mock_subprocess_run):
        """Verify RuntimeError is raised when git fails."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=128,
            stderr="fatal: not a git repository",
        )
        repo_dir = Path("/tmp/my-repo")

        with pytest.raises(RuntimeError, match="Failed to list tags"):
            tag_exists(repo_dir, "v1.0.0")


class TestCloneAtCommit:
    """Tests for clone_at_commit."""

    def test_clones_and_checks_out_commit(self, mock_subprocess_run):
        """Verify clone and checkout are called in sequence."""
        mock_subprocess_run.return_value = _make_completed_process()
        target_dir = Path("/tmp/clone-target")

        clone_at_commit(
            "https://github.com/org/repo.git",
            "abc1234",
            target_dir,
        )

        assert mock_subprocess_run.call_count == 2
        # First call: clone
        mock_subprocess_run.assert_any_call(
            ["git", "clone", "https://github.com/org/repo.git", "/tmp/clone-target"],
            capture_output=True,
            text=True,
        )
        # Second call: checkout
        mock_subprocess_run.assert_any_call(
            ["git", "checkout", "abc1234"],
            cwd="/tmp/clone-target",
            capture_output=True,
            text=True,
        )

    def test_raises_on_clone_failure(self, mock_subprocess_run):
        """Verify RuntimeError when clone fails."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=128,
            stderr="fatal: repository not found",
        )
        target_dir = Path("/tmp/clone-target")

        with pytest.raises(RuntimeError, match="Failed to clone repository"):
            clone_at_commit(
                "https://github.com/org/repo.git",
                "abc1234",
                target_dir,
            )

    def test_raises_on_checkout_failure(self, mock_subprocess_run):
        """Verify RuntimeError when checkout fails after successful clone."""
        # First call (clone) succeeds, second call (checkout) fails
        mock_subprocess_run.side_effect = [
            _make_completed_process(returncode=0),
            _make_completed_process(
                returncode=1,
                stderr="error: pathspec 'deadbeef' did not match any file(s)",
            ),
        ]
        target_dir = Path("/tmp/clone-target")

        with pytest.raises(RuntimeError, match="Failed to checkout commit"):
            clone_at_commit(
                "https://github.com/org/repo.git",
                "deadbeef",
                target_dir,
            )

    def test_error_on_clone_includes_repo_uri(self, mock_subprocess_run):
        """Verify clone error message includes the repository URI."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=128,
            stderr="fatal: could not read from remote",
        )
        target_dir = Path("/tmp/clone-target")

        with pytest.raises(RuntimeError) as exc_info:
            clone_at_commit(
                "git@github.com:org/private.git",
                "abc1234",
                target_dir,
            )

        assert "git@github.com:org/private.git" in str(exc_info.value)


class TestGetTagMessage:
    """Tests for get_tag_message."""

    def test_returns_tag_message_stripped(self, mock_subprocess_run):
        """Verify tag message is returned with trailing whitespace stripped."""
        tag_content = "git_commit_id: abc1234\ncontexts:\n  - production\n"
        mock_subprocess_run.return_value = _make_completed_process(
            stdout=tag_content + "\n\n",
        )
        repo_dir = Path("/tmp/my-repo")

        result = get_tag_message(repo_dir, "workflow/v1__202507")

        assert result == tag_content.strip()
        mock_subprocess_run.assert_called_once_with(
            ["git", "tag", "-l", "--format=%(contents)", "workflow/v1__202507"],
            cwd="/tmp/my-repo",
            capture_output=True,
            text=True,
        )

    def test_returns_empty_for_nonexistent_tag(self, mock_subprocess_run):
        """Verify empty string for a tag with no message."""
        mock_subprocess_run.return_value = _make_completed_process(stdout="")
        repo_dir = Path("/tmp/my-repo")

        result = get_tag_message(repo_dir, "nonexistent")

        assert result == ""

    def test_raises_on_git_failure(self, mock_subprocess_run):
        """Verify RuntimeError is raised when git fails."""
        mock_subprocess_run.return_value = _make_completed_process(
            returncode=1,
            stderr="error: some git error",
        )
        repo_dir = Path("/tmp/my-repo")

        with pytest.raises(RuntimeError, match="Failed to retrieve message for tag"):
            get_tag_message(repo_dir, "v1.0.0")

    def test_preserves_multiline_yaml_content(self, mock_subprocess_run):
        """Verify multiline YAML content is preserved correctly."""
        yaml_message = (
            "git_commit_id: abc1234def5678\n"
            "contexts:\n"
            "  - development\n"
            "  - production\n"
            "patch_names:\n"
            "  - fix-memory\n"
            "release_status: DRAFT\n"
            "workflow_version_description: Initial deploy"
        )
        mock_subprocess_run.return_value = _make_completed_process(
            stdout=yaml_message + "\n\n",
        )
        repo_dir = Path("/tmp/my-repo")

        result = get_tag_message(repo_dir, "oncoanalyser/2.2.0__20250715")

        assert result == yaml_message
