"""Unit tests for nf_ica_cli.validators module."""

import pytest

from nf_ica_cli.validators import (
    validate_context,
    validate_git_commit_id,
    validate_patch_name,
    validate_release_status,
)


class TestValidateGitCommitId:
    """Tests for validate_git_commit_id."""

    def test_valid_short_hash(self):
        assert validate_git_commit_id("abcdef0") is True

    def test_valid_full_hash(self):
        assert validate_git_commit_id("a" * 40) is True

    def test_valid_20_char_hash(self):
        assert validate_git_commit_id("1234567890abcdef1234") is True

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("abcdef")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("a" * 41)

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("ABCDEF0")

    def test_rejects_non_hex(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("ghijklm")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid git commit ID"):
            validate_git_commit_id("abcdef 1234567")


class TestValidatePatchName:
    """Tests for validate_patch_name."""

    def test_valid_alphanumeric(self):
        assert validate_patch_name("myPatch123") is True

    def test_valid_with_hyphens(self):
        assert validate_patch_name("my-patch") is True

    def test_valid_with_underscores(self):
        assert validate_patch_name("my_patch") is True

    def test_valid_mixed(self):
        assert validate_patch_name("fix-issue_42-v2") is True

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_patch_name("")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid patch name"):
            validate_patch_name("my patch")

    def test_rejects_dots(self):
        with pytest.raises(ValueError, match="Invalid patch name"):
            validate_patch_name("my.patch")

    def test_rejects_slashes(self):
        with pytest.raises(ValueError, match="Invalid patch name"):
            validate_patch_name("my/patch")

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="Invalid patch name"):
            validate_patch_name("patch@name!")


class TestValidateReleaseStatus:
    """Tests for validate_release_status."""

    def test_accepts_draft(self):
        assert validate_release_status("DRAFT") is True

    def test_accepts_released(self):
        assert validate_release_status("RELEASED") is True

    def test_rejects_lowercase_draft(self):
        with pytest.raises(ValueError, match="Invalid release status"):
            validate_release_status("draft")

    def test_rejects_lowercase_released(self):
        with pytest.raises(ValueError, match="Invalid release status"):
            validate_release_status("released")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid release status"):
            validate_release_status("")

    def test_rejects_other_values(self):
        with pytest.raises(ValueError, match="Invalid release status"):
            validate_release_status("PENDING")

    def test_error_message_lists_valid_options(self):
        with pytest.raises(ValueError, match="DRAFT, RELEASED"):
            validate_release_status("INVALID")


class TestValidateContext:
    """Tests for validate_context."""

    def test_accepts_valid_context(self):
        contexts = ["development", "production", "staging"]
        assert validate_context("production", contexts) is True

    def test_accepts_first_context(self):
        contexts = ["development", "production"]
        assert validate_context("development", contexts) is True

    def test_rejects_invalid_context(self):
        contexts = ["development", "production"]
        with pytest.raises(ValueError, match="Invalid context"):
            validate_context("staging", contexts)

    def test_rejects_with_empty_list(self):
        with pytest.raises(ValueError, match="Invalid context"):
            validate_context("production", [])

    def test_error_message_lists_available(self):
        contexts = ["development", "production"]
        with pytest.raises(ValueError, match="development, production"):
            validate_context("staging", contexts)

    def test_case_sensitive(self):
        contexts = ["production"]
        with pytest.raises(ValueError, match="Invalid context"):
            validate_context("Production", contexts)
