"""Unit tests for the ``collect-all-patches`` CLI argument parsing.

These tests exercise ``nf_ica_cli.cli.main`` end-to-end through the two-pass
docopt dispatch, driving it with a patched ``sys.argv``. The focus is purely on
argument parsing and dispatch, so the config loading (``find_config_repo`` and
``load_and_validate_config``) and the ``handle_collect_all_patches`` handler are
mocked at their import sites. This lets each test assert:

* all four required options are parsed and forwarded to the handler,
* a missing required option errors on stderr and exits with status 1,
* an unrecognized option errors on stderr and exits with status 1,
* ``--help`` prints the usage listing all four options to stdout and exits 0.

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""

from unittest.mock import MagicMock, patch

import pytest

from nf_ica_cli.cli import main

REPO_URI = "https://github.com/example/workflow.git"
COMMIT_ID = "abc123def456"
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PIPELINE_ID = "22222222-2222-2222-2222-222222222222"


def _exit_status(exc: SystemExit) -> int:
    """Map a ``SystemExit`` code to the process exit status CPython would use.

    ``None`` and ``0`` -> 0, any other ``int`` -> that int, and any non-``int``
    (e.g. docopt's usage-string ``DocoptExit`` code) -> 1.
    """
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _run_main(argv: list[str]):
    """Invoke ``main()`` with a patched ``sys.argv``.

    ``argv[0]`` mimics the program name; the remaining entries are the CLI
    arguments docopt parses.
    """
    with patch("sys.argv", ["nf-ica"] + argv):
        main()


class TestValidParsing:
    """All four required options are parsed and dispatched to the handler."""

    def test_all_four_args_parsed_and_dispatched(self):
        """Every required option reaches the handler as its named string value."""
        with patch("nf_ica_cli.config.find_config_repo") as mock_find, patch(
            "nf_ica_cli.config.load_and_validate_config"
        ) as mock_load, patch(
            "nf_ica_cli.handlers.collect_all_patches.handle_collect_all_patches"
        ) as mock_handler:
            config_repo = MagicMock(name="config_repo")
            app_config = MagicMock(name="app_config")
            mock_find.return_value = config_repo
            mock_load.return_value = app_config

            _run_main(
                [
                    "collect-all-patches",
                    f"--repo-uri={REPO_URI}",
                    f"--commit-id={COMMIT_ID}",
                    f"--project-id={PROJECT_ID}",
                    f"--pipeline-id={PIPELINE_ID}",
                ]
            )

            mock_handler.assert_called_once()
            args, _kwargs = mock_handler.call_args
            parsed_args, passed_config, passed_repo = args
            assert parsed_args["--repo-uri"] == REPO_URI
            assert parsed_args["--commit-id"] == COMMIT_ID
            assert parsed_args["--project-id"] == PROJECT_ID
            assert parsed_args["--pipeline-id"] == PIPELINE_ID
            assert parsed_args["collect-all-patches"] is True
            assert passed_config is app_config
            assert passed_repo is config_repo


class TestMissingArgs:
    """Each missing required option aborts with a stderr error and exit 1."""

    @pytest.mark.parametrize(
        "omit",
        ["--repo-uri", "--commit-id", "--project-id", "--pipeline-id"],
    )
    def test_missing_required_arg_exits_1(self, omit, capsys):
        """Dropping any single required option triggers a docopt usage error."""
        all_flags = {
            "--repo-uri": REPO_URI,
            "--commit-id": COMMIT_ID,
            "--project-id": PROJECT_ID,
            "--pipeline-id": PIPELINE_ID,
        }
        argv = ["collect-all-patches"] + [
            f"{flag}={value}" for flag, value in all_flags.items() if flag != omit
        ]

        # The handler must never run when parsing fails.
        with patch(
            "nf_ica_cli.handlers.collect_all_patches.handle_collect_all_patches"
        ) as mock_handler:
            with pytest.raises(SystemExit) as exc_info:
                _run_main(argv)

            mock_handler.assert_not_called()

        # docopt raises DocoptExit (a SystemExit subclass) whose ``code`` is the
        # usage message string. A non-empty, non-None SystemExit code maps to a
        # process exit status of 1, and Python prints that message to stderr.
        assert _exit_status(exc_info.value) == 1
        assert "Usage:" in str(exc_info.value.code)


class TestUnrecognizedArg:
    """An unrecognized option aborts with a stderr error and exit 1."""

    def test_unrecognized_arg_exits_1(self, capsys):
        with patch(
            "nf_ica_cli.handlers.collect_all_patches.handle_collect_all_patches"
        ) as mock_handler:
            with pytest.raises(SystemExit) as exc_info:
                _run_main(
                    [
                        "collect-all-patches",
                        f"--repo-uri={REPO_URI}",
                        f"--commit-id={COMMIT_ID}",
                        f"--project-id={PROJECT_ID}",
                        f"--pipeline-id={PIPELINE_ID}",
                        "--bogus-flag=nope",
                    ]
                )

            mock_handler.assert_not_called()

        assert _exit_status(exc_info.value) == 1
        assert "Usage:" in str(exc_info.value.code)


class TestHelp:
    """``--help`` prints usage listing all four options and exits 0."""

    def test_help_lists_all_four_options_and_exits_0(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _run_main(["collect-all-patches", "--help"])

        # docopt's --help exits with code None, which maps to a 0 exit status.
        assert exc_info.value.code in (0, None)

        captured = capsys.readouterr()
        help_text = captured.out
        assert "--repo-uri" in help_text
        assert "--commit-id" in help_text
        assert "--project-id" in help_text
        assert "--pipeline-id" in help_text
