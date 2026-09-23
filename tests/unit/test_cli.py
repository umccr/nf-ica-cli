"""Unit tests for CLI argument parsing.

Tests the docopt usage string parsing directly without running the full CLI,
avoiding the need for a config repo or any external dependencies.
"""

import pytest
from docopt import docopt, DocoptExit

from nf_ica_cli.cli import __doc__ as cli_doc, _SUBCMD_USAGE


# --- Helper ---


def parse_top_level(argv: list[str]) -> dict:
    """Parse argv using the top-level CLI docstring (options_first=True)."""
    return docopt(cli_doc, argv=argv, version="nf-ica-cli 0.1.0", options_first=True)


def parse_args(argv: list[str]) -> dict:
    """Parse argv using the two-pass approach matching the real CLI.

    First pass identifies the command, second pass parses its options.
    """
    top_args = docopt(cli_doc, argv=argv, version="nf-ica-cli 0.1.0", options_first=True)
    command = top_args["<command>"]
    if command not in _SUBCMD_USAGE:
        raise SystemExit(f"Error: Unknown command '{command}'.")
    sub_argv = [command] + top_args["<args>"]
    args = docopt(_SUBCMD_USAGE[command], argv=sub_argv)
    return args


# --- Test valid argument combinations for each subcommand ---


class TestRegisterPatch:
    """Test register-patch subcommand argument parsing."""

    def test_all_required_flags(self):
        args = parse_args([
            "register-patch",
            "--file=/tmp/my-patch.txt",
            "--name=my-patch",
            "--description=A test patch",
        ])
        assert args["register-patch"] is True
        assert args["--file"] == "/tmp/my-patch.txt"
        assert args["--name"] == "my-patch"
        assert args["--description"] == "A test patch"

    def test_missing_file_flag(self):
        with pytest.raises(SystemExit):
            parse_args(["register-patch", "--name=my-patch", "--description=desc"])

    def test_missing_name_flag(self):
        with pytest.raises(SystemExit):
            parse_args(["register-patch", "--file=/tmp/f.txt", "--description=desc"])

    def test_missing_description_flag(self):
        with pytest.raises(SystemExit):
            parse_args(["register-patch", "--file=/tmp/f.txt", "--name=my-patch"])


class TestAddWorkflowVersion:
    """Test add-workflow-version subcommand argument parsing."""

    def test_all_required_flags(self):
        args = parse_args([
            "add-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-repo-uri=https://github.com/umccr/oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--workflow-ica-nextflow-version=24.04.4",
        ])
        assert args["add-workflow-version"] is True
        assert args["--workflow-name"] == "oncoanalyser"
        assert args["--workflow-repo-uri"] == "https://github.com/umccr/oncoanalyser"
        assert args["--workflow-version-tag"] == "2.2.0"
        assert args["--workflow-version-git-commit-id"] == "abc1234"
        assert args["--workflow-version-context"] == ["production"]
        assert args["--workflow-ica-nextflow-version"] == "24.04.4"

    def test_repeated_context_flags(self):
        args = parse_args([
            "add-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-repo-uri=https://github.com/umccr/oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--workflow-version-context=development",
            "--workflow-ica-nextflow-version=24.04.4",
        ])
        assert args["--workflow-version-context"] == ["production", "development"]

    def test_missing_workflow_name(self):
        with pytest.raises(SystemExit):
            parse_args([
                "add-workflow-version",
                "--workflow-repo-uri=https://github.com/umccr/oncoanalyser",
                "--workflow-version-tag=2.2.0",
                "--workflow-version-git-commit-id=abc1234",
                "--workflow-version-context=production",
                "--workflow-ica-nextflow-version=24.04.4",
            ])

    def test_missing_context(self):
        with pytest.raises(SystemExit):
            parse_args([
                "add-workflow-version",
                "--workflow-name=oncoanalyser",
                "--workflow-repo-uri=https://github.com/umccr/oncoanalyser",
                "--workflow-version-tag=2.2.0",
                "--workflow-version-git-commit-id=abc1234",
                "--workflow-ica-nextflow-version=24.04.4",
            ])


class TestMakeWorkflowVersion:
    """Test deploy-workflow-version subcommand argument parsing."""

    def test_all_required_flags(self):
        args = parse_args([
            "deploy-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--release-status=DRAFT",
        ])
        assert args["deploy-workflow-version"] is True
        assert args["--workflow-name"] == "oncoanalyser"
        assert args["--workflow-version-tag"] == "2.2.0"
        assert args["--workflow-version-git-commit-id"] == "abc1234"
        assert args["--workflow-version-context"] == ["production"]
        assert args["--release-status"] == "DRAFT"
        assert args["--workflow-patch-name"] == []
        assert args["--workflow-version-description"] is None

    def test_with_optional_patch_name(self):
        args = parse_args([
            "deploy-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--workflow-patch-name=esvee-high-memory",
            "--release-status=DRAFT",
        ])
        assert args["--workflow-patch-name"] == ["esvee-high-memory"]

    def test_with_multiple_patch_names(self):
        args = parse_args([
            "deploy-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--workflow-patch-name=patch-a",
            "--workflow-patch-name=patch-b",
            "--release-status=DRAFT",
        ])
        assert args["--workflow-patch-name"] == ["patch-a", "patch-b"]

    def test_with_optional_description(self):
        args = parse_args([
            "deploy-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--release-status=RELEASED",
            "--workflow-version-description=Initial production release",
        ])
        assert args["--workflow-version-description"] == "Initial production release"

    def test_with_multiple_contexts(self):
        args = parse_args([
            "deploy-workflow-version",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--workflow-version-git-commit-id=abc1234",
            "--workflow-version-context=production",
            "--workflow-version-context=staging",
            "--release-status=DRAFT",
        ])
        assert args["--workflow-version-context"] == ["production", "staging"]

    def test_missing_release_status(self):
        with pytest.raises(SystemExit):
            parse_args([
                "deploy-workflow-version",
                "--workflow-name=oncoanalyser",
                "--workflow-version-tag=2.2.0",
                "--workflow-version-git-commit-id=abc1234",
                "--workflow-version-context=production",
            ])


class TestUpdateWorkflowVersionReleaseStatus:
    """Test update-workflow-version-release-status subcommand argument parsing."""

    def test_all_required_flags(self):
        args = parse_args([
            "update-workflow-version-release-status",
            "--workflow-name=oncoanalyser",
            "--workflow-version-tag=2.2.0",
            "--release-status=RELEASED",
        ])
        assert args["update-workflow-version-release-status"] is True
        assert args["--workflow-name"] == "oncoanalyser"
        assert args["--workflow-version-tag"] == "2.2.0"
        assert args["--release-status"] == "RELEASED"

    def test_missing_workflow_name(self):
        with pytest.raises(SystemExit):
            parse_args([
                "update-workflow-version-release-status",
                "--workflow-version-tag=2.2.0",
                "--release-status=RELEASED",
            ])

    def test_missing_release_status(self):
        with pytest.raises(SystemExit):
            parse_args([
                "update-workflow-version-release-status",
                "--workflow-name=oncoanalyser",
                "--workflow-version-tag=2.2.0",
            ])


class TestGhActionsDeployWorkflow:
    """Test gh-actions-deploy-workflow subcommand argument parsing."""

    def test_all_required_flags(self):
        args = parse_args([
            "gh-actions-deploy-workflow",
            "--workflow-name=oncoanalyser",
            "--workflow-version=2.2.0",
            "--annotated-tag-name=oncoanalyser/2.2.0__20250715143022",
        ])
        assert args["gh-actions-deploy-workflow"] is True
        assert args["--workflow-name"] == "oncoanalyser"
        assert args["--workflow-version"] == "2.2.0"
        assert args["--annotated-tag-name"] == "oncoanalyser/2.2.0__20250715143022"

    def test_missing_annotated_tag_name(self):
        with pytest.raises(SystemExit):
            parse_args([
                "gh-actions-deploy-workflow",
                "--workflow-name=oncoanalyser",
                "--workflow-version=2.2.0",
            ])

    def test_missing_workflow_version(self):
        with pytest.raises(SystemExit):
            parse_args([
                "gh-actions-deploy-workflow",
                "--workflow-name=oncoanalyser",
                "--annotated-tag-name=oncoanalyser/2.2.0__20250715143022",
            ])


# --- Test --help and --version ---


class TestHelpAndVersion:
    """Test --help and --version options."""

    def test_help_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args(["--help"])

    def test_short_help_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args(["-h"])

    def test_version_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args(["--version"])


# --- Test no subcommand ---


class TestNoSubcommand:
    """Test invocation without a subcommand."""

    def test_no_args_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_invalid_subcommand_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args(["invalid-command"])


# --- Test subcommand boolean flags are mutually exclusive ---


class TestSubcommandExclusivity:
    """Verify only one subcommand is active at a time.

    With two-pass docopt parsing, each subcommand's args dict only contains
    the active command's boolean key. We verify the correct command is True.
    """

    def test_register_patch_is_active(self):
        args = parse_args([
            "register-patch",
            "--file=/tmp/f.txt",
            "--name=p",
            "--description=d",
        ])
        assert args["register-patch"] is True
        assert "add-workflow-version" not in args
        assert "deploy-workflow-version" not in args

    def test_add_workflow_version_is_active(self):
        args = parse_args([
            "add-workflow-version",
            "--workflow-name=wf",
            "--workflow-repo-uri=https://example.com/repo",
            "--workflow-version-tag=1.0.0",
            "--workflow-version-git-commit-id=abcdef1",
            "--workflow-version-context=dev",
            "--workflow-ica-nextflow-version=24.04.4",
        ])
        assert args["add-workflow-version"] is True
        assert "register-patch" not in args
        assert "deploy-workflow-version" not in args
