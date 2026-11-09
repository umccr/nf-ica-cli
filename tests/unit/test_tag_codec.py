"""Unit tests for nf_ica_cli.tag_codec module."""

import re
from unittest.mock import patch

import pytest

from nf_ica_cli.tag_codec import (
    TagMetadata,
    decode_tag_message,
    encode_tag_message,
    make_tag_name,
)


class TestEncodeTagMessage:
    """Tests for encode_tag_message."""

    def test_encodes_all_five_keys(self):
        metadata = TagMetadata(
            git_commit_id="abc1234",
            contexts=["production"],
            patch_names=["fix-memory"],
            release_status="DRAFT",
            workflow_version_description="Initial release",
        )
        result = encode_tag_message(metadata)
        assert "git_commit_id:" in result
        assert "contexts:" in result
        assert "patch_names:" in result
        assert "release_status:" in result
        assert "workflow_version_description:" in result

    def test_encodes_empty_patch_names_as_empty_list(self):
        metadata = TagMetadata(
            git_commit_id="abc1234",
            contexts=["dev"],
            patch_names=[],
            release_status="DRAFT",
            workflow_version_description="",
        )
        result = encode_tag_message(metadata)
        assert "patch_names: []" in result

    def test_encodes_multiple_contexts(self):
        metadata = TagMetadata(
            git_commit_id="deadbeef1234567",
            contexts=["production", "staging"],
            patch_names=[],
            release_status="RELEASED",
            workflow_version_description="Multi-context deploy",
        )
        result = encode_tag_message(metadata)
        assert "production" in result
        assert "staging" in result

    def test_encodes_empty_description(self):
        metadata = TagMetadata(
            git_commit_id="abc1234",
            contexts=["dev"],
            patch_names=[],
            release_status="DRAFT",
            workflow_version_description="",
        )
        result = encode_tag_message(metadata)
        assert "workflow_version_description: ''" in result


class TestDecodeTagMessage:
    """Tests for decode_tag_message."""

    def test_decodes_valid_message(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- production\n"
            "patch_names:\n"
            "- fix-memory\n"
            "release_status: DRAFT\n"
            "workflow_version_description: Initial release\n"
        )
        result = decode_tag_message(message)
        assert result.git_commit_id == "abc1234"
        assert result.contexts == ["production"]
        assert result.patch_names == ["fix-memory"]
        assert result.release_status == "DRAFT"
        assert result.workflow_version_description == "Initial release"

    def test_decodes_empty_patch_names(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- dev\n"
            "patch_names: []\n"
            "release_status: RELEASED\n"
            "workflow_version_description: ''\n"
        )
        result = decode_tag_message(message)
        assert result.patch_names == []
        assert result.workflow_version_description == ""

    def test_raises_on_missing_key(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- production\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="missing key.*patch_names"):
            decode_tag_message(message)

    def test_raises_on_unknown_key(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- production\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
            "extra_key: unexpected\n"
        )
        with pytest.raises(ValueError, match="unknown key.*extra_key"):
            decode_tag_message(message)

    def test_raises_on_type_mismatch_contexts_not_list(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts: production\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="'contexts' must be list"):
            decode_tag_message(message)

    def test_raises_on_type_mismatch_git_commit_id_not_string(self):
        message = (
            "git_commit_id: 1234567\n"
            "contexts:\n"
            "- production\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        # 1234567 is parsed as int by YAML
        with pytest.raises(ValueError, match="'git_commit_id' must be non-empty string"):
            decode_tag_message(message)

    def test_raises_on_empty_git_commit_id(self):
        message = (
            "git_commit_id: ''\n"
            "contexts:\n"
            "- production\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="git_commit_id.*non-empty"):
            decode_tag_message(message)

    def test_raises_on_empty_contexts(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts: []\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="contexts.*at least one"):
            decode_tag_message(message)

    def test_raises_on_invalid_yaml(self):
        message = "not: valid: yaml: {{{{"
        with pytest.raises(ValueError, match="failed to parse YAML"):
            decode_tag_message(message)

    def test_raises_on_empty_document(self):
        with pytest.raises(ValueError, match="empty document"):
            decode_tag_message("")

    def test_raises_on_non_string_in_contexts_list(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- 123\n"
            "patch_names: []\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="contexts\\[0\\].*must be a string"):
            decode_tag_message(message)

    def test_raises_on_non_string_in_patch_names_list(self):
        message = (
            "git_commit_id: abc1234\n"
            "contexts:\n"
            "- production\n"
            "patch_names:\n"
            "- 999\n"
            "release_status: DRAFT\n"
            "workflow_version_description: ''\n"
        )
        with pytest.raises(ValueError, match="patch_names\\[0\\].*must be a string"):
            decode_tag_message(message)


class TestRoundTrip:
    """Test encode/decode round-trip."""

    def test_round_trip_preserves_values(self):
        original = TagMetadata(
            git_commit_id="deadbeef1234567",
            contexts=["production", "staging"],
            patch_names=["fix-memory", "add-logging"],
            release_status="RELEASED",
            workflow_version_description="Full deployment",
        )
        encoded = encode_tag_message(original)
        decoded = decode_tag_message(encoded)

        assert decoded.git_commit_id == original.git_commit_id
        assert decoded.contexts == original.contexts
        assert decoded.patch_names == original.patch_names
        assert decoded.release_status == original.release_status
        assert decoded.workflow_version_description == original.workflow_version_description

    def test_round_trip_with_empty_optionals(self):
        original = TagMetadata(
            git_commit_id="abc1234",
            contexts=["dev"],
            patch_names=[],
            release_status="DRAFT",
            workflow_version_description="",
        )
        encoded = encode_tag_message(original)
        decoded = decode_tag_message(encoded)

        assert decoded.git_commit_id == original.git_commit_id
        assert decoded.contexts == original.contexts
        assert decoded.patch_names == original.patch_names
        assert decoded.release_status == original.release_status
        assert decoded.workflow_version_description == original.workflow_version_description


class TestMakeTagName:
    """Tests for make_tag_name."""

    def test_format_matches_expected_pattern(self):
        result = make_tag_name("oncoanalyser", "2.2.0")
        pattern = r"^oncoanalyser/2\.2\.0__\d{14}$"
        assert re.match(pattern, result)

    def test_includes_workflow_name_and_version(self):
        result = make_tag_name("my-pipeline", "1.0.0")
        assert result.startswith("my-pipeline/1.0.0__")

    @patch("nf_ica_cli.tag_codec.datetime")
    def test_uses_utc_timestamp(self, mock_datetime):
        from datetime import timezone

        mock_now = mock_datetime.now.return_value
        mock_now.strftime.return_value = "20250715143022"
        mock_datetime.now.return_value = mock_now

        result = make_tag_name("oncoanalyser", "2.2.0")

        mock_datetime.now.assert_called_once_with(timezone.utc)
        assert result == "oncoanalyser/2.2.0__20250715143022"

    def test_double_underscore_separator(self):
        result = make_tag_name("workflow", "v1")
        assert "__" in result
        parts = result.split("__")
        assert len(parts) == 2
        assert parts[0] == "workflow/v1"
