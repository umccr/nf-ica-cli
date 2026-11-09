"""Unit tests for the interactive patch prompter flow.

Covers ``prompt_for_patch_metadata`` from ``nf_ica_cli.patch_prompter``:
default-name acceptance, custom name, invalid-name re-prompt, taken-name
re-prompt, empty-description re-prompt, duplicate skip, and the non-TTY
``SystemExit`` fail-fast path.

``input()`` and ``sys.stdin.isatty()`` are mocked so the interactive flow can
be driven deterministically. ``input`` is patched with a ``side_effect`` list
that supplies the sequence of user responses; ``sys.stdin.isatty`` is patched
to simulate an interactive (or non-interactive) terminal.

Validates: Requirements 5.2, 5.5, 5.6, 5.7, 5.8, 5.9, 5.11
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.patch_prompter import (
    PatchPromptResult,
    prompt_for_patch_metadata,
)
from nf_ica_cli.patches import PatchEntry


# A patch file path shown to the user for reference. Its content is never read
# by the prompter (the MD5 is passed in directly), so it does not need to exist.
PATCH_FILE_PATH = Path("/tmp/some-patch.diff")
MD5SUM = "0123456789abcdef0123456789abcdef"
WORKFLOW_ID = "myworkflow"


def _existing_patch(name: str, md5sum: str) -> PatchEntry:
    """Build a PatchEntry for use in the existing-patches registry list."""
    return PatchEntry(
        name=name,
        path=f"patches/{md5sum}.txt",
        md5sum=md5sum,
        description="an existing patch",
    )


def _prompt(inputs, existing_patches=None, md5sum=MD5SUM, isatty=True):
    """Run ``prompt_for_patch_metadata`` with mocked input() and isatty().

    Args:
        inputs: side_effect list feeding successive ``input()`` calls.
        existing_patches: registry list (defaults to empty).
        md5sum: the patch content MD5 to pass through.
        isatty: return value for ``sys.stdin.isatty()``.

    Returns:
        The PatchPromptResult produced by the prompter.
    """
    with patch("nf_ica_cli.patch_prompter.sys.stdin.isatty", return_value=isatty), patch(
        "builtins.input", side_effect=list(inputs)
    ):
        return prompt_for_patch_metadata(
            relative_path="conf/ica.config",
            patch_file_path=PATCH_FILE_PATH,
            existing_patches=existing_patches if existing_patches is not None else [],
            md5sum=md5sum,
            workflow_identifier=WORKFLOW_ID,
        )


class TestNonTty:
    """The prompter requires an interactive terminal (Requirement 5.11)."""

    def test_non_tty_raises_system_exit(self):
        """SystemExit is raised when stdin is not a TTY, before any prompting."""
        with patch(
            "nf_ica_cli.patch_prompter.sys.stdin.isatty", return_value=False
        ), patch("builtins.input") as mock_input:
            with pytest.raises(SystemExit) as exc_info:
                prompt_for_patch_metadata(
                    relative_path="conf/ica.config",
                    patch_file_path=PATCH_FILE_PATH,
                    existing_patches=[],
                    md5sum=MD5SUM,
                    workflow_identifier=WORKFLOW_ID,
                )

        # Non-zero exit status.
        assert exc_info.value.code != 0
        # No prompting was attempted.
        mock_input.assert_not_called()

    def test_non_tty_writes_error_to_stderr(self, capsys):
        """A descriptive interactive-mode error is written to stderr."""
        with patch(
            "nf_ica_cli.patch_prompter.sys.stdin.isatty", return_value=False
        ), patch("builtins.input"):
            with pytest.raises(SystemExit):
                prompt_for_patch_metadata(
                    relative_path="conf/ica.config",
                    patch_file_path=PATCH_FILE_PATH,
                    existing_patches=[],
                    md5sum=MD5SUM,
                    workflow_identifier=WORKFLOW_ID,
                )

        captured = capsys.readouterr()
        assert "INTERACTIVE" in captured.err
        assert captured.out == "" or "Patch for" not in captured.out


class TestNamePrompt:
    """Name prompting: default acceptance, custom, and re-prompt paths."""

    def test_accepts_suggested_default_on_empty_input(self):
        """Pressing Enter (empty input) accepts the suggested default name.

        Validates: Requirements 5.5.
        """
        # input 1: empty -> accept suggested name; input 2: description.
        result = _prompt(["", "A useful description"])

        assert result.skip is False
        # Suggested name is <workflow>_<slug of conf/ica.config> == myworkflow_conf_ica
        assert result.name == "myworkflow_conf_ica"
        assert result.description == "A useful description"

    def test_accepts_custom_name(self):
        """A non-empty custom name overrides the suggested default.

        Validates: Requirements 5.5.
        """
        result = _prompt(["custom-name", "desc"])

        assert result.skip is False
        assert result.name == "custom-name"
        assert result.description == "desc"

    def test_reprompts_on_invalid_name_then_accepts(self, capsys):
        """An invalid name is rejected and re-prompted until valid.

        Validates: Requirements 5.7.
        """
        # input 1: invalid (space + '!') -> re-prompt; input 2: valid; input 3: desc.
        result = _prompt(["bad name!", "good-name", "desc"])

        assert result.skip is False
        assert result.name == "good-name"
        assert result.description == "desc"

        # A validation error was surfaced to stderr for the invalid attempt.
        captured = capsys.readouterr()
        assert "VALIDATION" in captured.err

    def test_reprompts_on_taken_name_then_accepts(self, capsys):
        """A name already in the registry is rejected and re-prompted.

        Validates: Requirements 5.8.
        """
        existing = [_existing_patch("taken-name", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")]

        # input 1: taken -> re-prompt; input 2: free name; input 3: desc.
        result = _prompt(
            ["taken-name", "fresh-name", "desc"],
            existing_patches=existing,
        )

        assert result.skip is False
        assert result.name == "fresh-name"
        assert result.description == "desc"

        captured = capsys.readouterr()
        assert "already registered" in captured.err


class TestDescriptionPrompt:
    """Description prompting requires a non-empty value (Requirement 5.6)."""

    def test_reprompts_on_empty_description_then_accepts(self, capsys):
        """An empty description is rejected and re-prompted until non-empty."""
        # input 1: name; input 2: empty desc -> re-prompt; input 3: real desc.
        result = _prompt(["a-name", "", "finally a description"])

        assert result.skip is False
        assert result.name == "a-name"
        assert result.description == "finally a description"

        captured = capsys.readouterr()
        # The empty-description error is printed to stdout.
        assert "Description must not be empty" in captured.out

    def test_whitespace_only_description_is_rejected(self):
        """A whitespace-only description is treated as empty and re-prompted."""
        result = _prompt(["a-name", "   ", "real description"])

        assert result.description == "real description"


class TestDuplicateSkip:
    """MD5-duplicate handling offers a skip option (Requirements 5.2, 5.9)."""

    def test_duplicate_skip_with_empty_input(self, capsys):
        """An MD5 duplicate offers skip; empty input (default Y) skips it."""
        existing = [_existing_patch("existing-name", MD5SUM)]

        # input 1: empty -> default 'Y' -> skip.
        result = _prompt([""], existing_patches=existing)

        assert result == PatchPromptResult(name="", description="", skip=True)

        # The duplicate notification shows the existing name, md5, and path.
        captured = capsys.readouterr()
        assert "existing-name" in captured.out
        assert MD5SUM in captured.out
        assert f"patches/{MD5SUM}.txt" in captured.out

    def test_duplicate_skip_with_yes(self):
        """Answering 'yes' to the skip prompt skips the duplicate patch."""
        existing = [_existing_patch("existing-name", MD5SUM)]

        result = _prompt(["yes"], existing_patches=existing)

        assert result.skip is True
        assert result.name == ""
        assert result.description == ""

    def test_duplicate_no_proceeds_to_registration(self):
        """Declining the skip prompt proceeds to name/description prompting."""
        existing = [_existing_patch("existing-name", MD5SUM)]

        # input 1: 'n' -> do not skip; input 2: name; input 3: desc.
        result = _prompt(
            ["n", "new-unique-name", "a description"],
            existing_patches=existing,
        )

        assert result.skip is False
        assert result.name == "new-unique-name"
        assert result.description == "a description"

    def test_duplicate_skip_reprompts_on_unrecognized_answer(self, capsys):
        """An unrecognized skip answer is re-prompted until y/n is given."""
        existing = [_existing_patch("existing-name", MD5SUM)]

        # input 1: 'maybe' -> re-prompt; input 2: 'y' -> skip.
        result = _prompt(["maybe", "y"], existing_patches=existing)

        assert result.skip is True

        captured = capsys.readouterr()
        assert "Please answer" in captured.out

    def test_no_duplicate_when_md5_differs(self):
        """An existing entry with a different MD5 does not trigger skip prompt."""
        existing = [_existing_patch("other-name", "ffffffffffffffffffffffffffffffff")]

        # No skip prompt: input 1: name; input 2: desc.
        result = _prompt(["my-name", "my desc"], existing_patches=existing)

        assert result.skip is False
        assert result.name == "my-name"
        assert result.description == "my desc"
