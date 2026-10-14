"""Unit tests for the patch manager module."""

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.patches import PatchEntry, apply_patches, compute_md5, register_patch


class TestComputeMd5:
    """Tests for compute_md5 function."""

    def test_computes_correct_md5_for_known_content(self, tmp_path):
        """MD5 of known content matches expected hash."""
        content = b"hello world\n"
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(content)

        expected = hashlib.md5(content).hexdigest()
        assert compute_md5(file_path) == expected

    def test_computes_correct_md5_for_empty_file(self, tmp_path):
        """MD5 of empty file matches known empty MD5."""
        file_path = tmp_path / "empty.txt"
        file_path.write_bytes(b"")

        expected = hashlib.md5(b"").hexdigest()
        assert compute_md5(file_path) == expected

    def test_returns_lowercase_hex_string(self, tmp_path):
        """MD5 digest is a lowercase hex string of length 32."""
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(b"some content")

        result = compute_md5(file_path)
        assert len(result) == 32
        assert result == result.lower()
        assert all(c in "0123456789abcdef" for c in result)

    def test_raises_file_not_found_for_missing_file(self, tmp_path):
        """Raises FileNotFoundError for nonexistent file."""
        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            compute_md5(missing)

    def test_same_content_produces_same_md5(self, tmp_path):
        """Identical content in different files produces same MD5."""
        content = b"identical content"
        file1 = tmp_path / "a.txt"
        file2 = tmp_path / "b.txt"
        file1.write_bytes(content)
        file2.write_bytes(content)

        assert compute_md5(file1) == compute_md5(file2)

    def test_different_content_produces_different_md5(self, tmp_path):
        """Different content produces different MD5."""
        file1 = tmp_path / "a.txt"
        file2 = tmp_path / "b.txt"
        file1.write_bytes(b"content A")
        file2.write_bytes(b"content B")

        assert compute_md5(file1) != compute_md5(file2)


class TestRegisterPatch:
    """Tests for register_patch function."""

    def test_registers_new_patch_successfully(self, tmp_path):
        """Successfully registers a new patch and copies file."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "patches").mkdir()

        source = tmp_path / "my_patch.diff"
        source.write_text("--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n")

        result = register_patch(
            config_repo=config_repo,
            source_file=source,
            name="my-patch",
            description="A test patch",
            existing_patches=[],
        )

        assert result.name == "my-patch"
        assert result.description == "A test patch"
        assert result.md5sum == compute_md5(source)
        assert result.path == f"patches/{result.md5sum}.txt"

        # Verify file was copied
        dest_path = config_repo / result.path
        assert dest_path.exists()
        assert dest_path.read_text() == source.read_text()

    def test_rejects_invalid_patch_name(self, tmp_path):
        """Raises ValueError for invalid patch name."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        source = tmp_path / "patch.diff"
        source.write_text("content")

        with pytest.raises(ValueError, match="Invalid patch name"):
            register_patch(
                config_repo=config_repo,
                source_file=source,
                name="invalid name!",
                description="desc",
                existing_patches=[],
            )

    def test_rejects_empty_patch_name(self, tmp_path):
        """Raises ValueError for empty patch name."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        source = tmp_path / "patch.diff"
        source.write_text("content")

        with pytest.raises(ValueError, match="must not be empty"):
            register_patch(
                config_repo=config_repo,
                source_file=source,
                name="",
                description="desc",
                existing_patches=[],
            )

    def test_rejects_duplicate_name(self, tmp_path):
        """Raises ValueError when patch name already exists."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        source = tmp_path / "patch.diff"
        source.write_text("content")

        existing = [
            PatchEntry(
                name="existing-patch",
                path="patches/abc123.txt",
                md5sum="abc123",
                description="existing",
            )
        ]

        with pytest.raises(ValueError, match="already registered"):
            register_patch(
                config_repo=config_repo,
                source_file=source,
                name="existing-patch",
                description="desc",
                existing_patches=existing,
            )

    def test_rejects_missing_source_file(self, tmp_path):
        """Raises FileNotFoundError when source file doesn't exist."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()

        with pytest.raises(FileNotFoundError, match="not found"):
            register_patch(
                config_repo=config_repo,
                source_file=tmp_path / "nonexistent.diff",
                name="my-patch",
                description="desc",
                existing_patches=[],
            )

    def test_skips_copy_when_md5_matches_existing(self, tmp_path):
        """Reuses existing path when MD5 matches."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "patches").mkdir()

        source = tmp_path / "patch.diff"
        source.write_text("shared content")
        md5sum = compute_md5(source)

        # Create existing entry with same md5
        existing_path = f"patches/{md5sum}.txt"
        (config_repo / existing_path).write_text("shared content")

        existing = [
            PatchEntry(
                name="other-patch",
                path=existing_path,
                md5sum=md5sum,
                description="other",
            )
        ]

        result = register_patch(
            config_repo=config_repo,
            source_file=source,
            name="new-name",
            description="new desc",
            existing_patches=existing,
        )

        assert result.md5sum == md5sum
        assert result.path == existing_path

    def test_validates_name_before_file_operations(self, tmp_path):
        """Name validation happens before checking file existence."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()

        # Source doesn't exist, but name is invalid — should fail on name first
        with pytest.raises(ValueError, match="Invalid patch name"):
            register_patch(
                config_repo=config_repo,
                source_file=tmp_path / "nonexistent.diff",
                name="bad name!",
                description="desc",
                existing_patches=[],
            )

    def test_creates_patches_directory_if_missing(self, tmp_path):
        """Creates the patches/ directory if it doesn't exist."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        # No patches/ directory

        source = tmp_path / "patch.diff"
        source.write_text("patch content")

        result = register_patch(
            config_repo=config_repo,
            source_file=source,
            name="new-patch",
            description="desc",
            existing_patches=[],
        )

        dest_path = config_repo / result.path
        assert dest_path.exists()


class TestApplyPatches:
    """Tests for apply_patches function."""

    def test_raises_for_unregistered_patch_name(self, tmp_path):
        """Raises ValueError when patch name is not in registry."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        with pytest.raises(ValueError, match="not registered"):
            apply_patches(
                repo_dir=repo_dir,
                patch_names=["nonexistent"],
                patches_registry=[],
                config_repo=tmp_path,
            )

    def test_raises_for_missing_patch_file(self, tmp_path):
        """Raises FileNotFoundError when patch file is missing from disk."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        config_repo = tmp_path / "config"
        config_repo.mkdir()

        registry = [
            PatchEntry(
                name="my-patch",
                path="patches/abc123.txt",
                md5sum="abc123",
                description="desc",
            )
        ]

        with pytest.raises(FileNotFoundError, match="missing"):
            apply_patches(
                repo_dir=repo_dir,
                patch_names=["my-patch"],
                patches_registry=registry,
                config_repo=config_repo,
            )

    @patch("nf_ica_cli.patches.subprocess.run")
    def test_calls_git_apply_with_correct_args(self, mock_run, tmp_path):
        """Calls git apply with the correct patch path and cwd."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        config_repo = tmp_path / "config"
        config_repo.mkdir()
        (config_repo / "patches").mkdir()
        patch_file = config_repo / "patches" / "abc123.txt"
        patch_file.write_text("patch content")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        registry = [
            PatchEntry(
                name="my-patch",
                path="patches/abc123.txt",
                md5sum="abc123",
                description="desc",
            )
        ]

        apply_patches(
            repo_dir=repo_dir,
            patch_names=["my-patch"],
            patches_registry=registry,
            config_repo=config_repo,
        )

        mock_run.assert_called_once_with(
            ["git", "apply", str(patch_file)],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        )

    @patch("nf_ica_cli.patches.subprocess.run")
    def test_applies_patches_in_order(self, mock_run, tmp_path):
        """Patches are applied in the order specified."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        config_repo = tmp_path / "config"
        config_repo.mkdir()
        (config_repo / "patches").mkdir()

        # Create two patch files
        patch1 = config_repo / "patches" / "md5_1.txt"
        patch2 = config_repo / "patches" / "md5_2.txt"
        patch1.write_text("patch 1")
        patch2.write_text("patch 2")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        registry = [
            PatchEntry(name="first", path="patches/md5_1.txt", md5sum="md5_1", description="first"),
            PatchEntry(name="second", path="patches/md5_2.txt", md5sum="md5_2", description="second"),
        ]

        apply_patches(
            repo_dir=repo_dir,
            patch_names=["first", "second"],
            patches_registry=registry,
            config_repo=config_repo,
        )

        assert mock_run.call_count == 2
        calls = mock_run.call_args_list
        assert str(patch1) in calls[0][0][0][2]
        assert str(patch2) in calls[1][0][0][2]

    @patch("nf_ica_cli.patches.subprocess.run")
    def test_raises_runtime_error_on_git_apply_failure(self, mock_run, tmp_path):
        """Raises RuntimeError with clear error when git apply fails."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        config_repo = tmp_path / "config"
        config_repo.mkdir()
        (config_repo / "patches").mkdir()
        patch_file = config_repo / "patches" / "abc123.txt"
        patch_file.write_text("bad patch")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error: patch does not apply"
        )

        registry = [
            PatchEntry(
                name="bad-patch",
                path="patches/abc123.txt",
                md5sum="abc123",
                description="desc",
            )
        ]

        with pytest.raises(RuntimeError, match="Failed to apply patch 'bad-patch'"):
            apply_patches(
                repo_dir=repo_dir,
                patch_names=["bad-patch"],
                patches_registry=registry,
                config_repo=config_repo,
            )

    def test_no_patches_is_a_noop(self, tmp_path):
        """Empty patch list does nothing."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        # Should complete without error
        apply_patches(
            repo_dir=repo_dir,
            patch_names=[],
            patches_registry=[],
            config_repo=tmp_path,
        )
