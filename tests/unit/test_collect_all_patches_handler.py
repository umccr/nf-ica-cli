"""Unit tests for nf_ica_cli.handlers.collect_all_patches orchestration.

Covers ``handle_collect_all_patches`` for the collect-all-patches subcommand:
the collaborator call sequence and argument passing, the missing-token
fail-fast, clone failure, pipeline export/API failure, the no-diffs path, and
temporary directory cleanup on both success and error.

The four collaborators are mocked at their import sites in
``nf_ica_cli.handlers.collect_all_patches`` so the handler's orchestration can
be exercised without a real git remote, ICA API, or interactive prompting:

* ``clone_at_commit``
* ``export_pipeline_source``
* ``generate_diffs``
* ``register_collected_patches``

``tempfile.mkdtemp`` is patched (at the handler's import site) to return real,
controllable directories so the ``finally`` block's ``shutil.rmtree`` cleanup
can be asserted by checking the directories no longer exist after the call.

Validates: Requirements 2.2, 2.3, 2.4, 3.6, 6.3, 7.2
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.config import AppConfig, IcaConfig, Workflow, WorkflowVersion
from nf_ica_cli.diff_generator import FileDiff
from nf_ica_cli.handlers.collect_all_patches import handle_collect_all_patches
from nf_ica_cli.patch_registrar import CollectedPatch
from nf_ica_cli.patches import PatchEntry

REPO_URI = "https://github.com/example/workflow.git"
COMMIT_ID = "abc123def456"
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PIPELINE_ID = "22222222-2222-2222-2222-222222222222"


def _make_args() -> dict:
    """Build a docopt-style args dict with the four required keys."""
    return {
        "--repo-uri": REPO_URI,
        "--commit-id": COMMIT_ID,
        "--project-id": PROJECT_ID,
        "--pipeline-id": PIPELINE_ID,
        "collect-all-patches": True,
    }


def _make_app_config(
    config_repo: Path,
    patches: list = None,
    workflows: list = None,
) -> AppConfig:
    """Build a minimal AppConfig with .patches and .workflows populated."""
    return AppConfig(
        config_repo=config_repo,
        workflows=workflows or [],
        contexts=[],
        ica_config=IcaConfig(tenants=[], default_nextflow_version=""),
        pipelines=[],
        patches=patches or [],
    )


@pytest.fixture
def token(monkeypatch):
    """Set a valid ICAV2_ACCESS_TOKEN for the duration of a test."""
    monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")


@pytest.fixture
def temp_dirs(tmp_path):
    """Two real temp dirs handed out by a patched tempfile.mkdtemp, in order.

    The handler calls ``tempfile.mkdtemp`` twice: first for the clone dir, then
    for the export dir. We create real directories so the handler's cleanup can
    actually remove them, and tests can assert they no longer exist afterwards.
    """
    clone_dir = tmp_path / "clone"
    export_dir = tmp_path / "export"
    clone_dir.mkdir()
    export_dir.mkdir()
    return clone_dir, export_dir


def _make_diff(relative_path: str = "main.nf") -> FileDiff:
    return FileDiff(
        relative_path=relative_path,
        diff_content=f"--- a/{relative_path}\n+++ b/{relative_path}\n",
        is_new_file=False,
        is_deleted=False,
    )


class TestMissingTokenFailFast:
    """No/empty ICAV2_ACCESS_TOKEN -> SystemExit before cloning.

    Validates: Requirements 7.2.
    """

    def test_unset_token_exits_before_clone(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ICAV2_ACCESS_TOKEN", raising=False)
        config = _make_app_config(tmp_path)

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit"
        ) as mock_clone, patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source"
        ) as mock_export, patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp"
        ) as mock_mkdtemp:
            with pytest.raises(SystemExit) as exc_info:
                handle_collect_all_patches(_make_args(), config, tmp_path)

        error_msg = str(exc_info.value)
        assert "[AUTH]" in error_msg
        assert "ICAV2_ACCESS_TOKEN" in error_msg
        # Fail-fast: no clone, no export, and no temp dirs were ever created.
        mock_clone.assert_not_called()
        mock_export.assert_not_called()
        mock_mkdtemp.assert_not_called()

    def test_empty_token_exits_before_clone(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "")
        config = _make_app_config(tmp_path)

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit"
        ) as mock_clone:
            with pytest.raises(SystemExit) as exc_info:
                handle_collect_all_patches(_make_args(), config, tmp_path)

        assert "[AUTH]" in str(exc_info.value)
        mock_clone.assert_not_called()


class TestHappyPath:
    """Clone -> export -> generate_diffs -> register, in order, with cleanup.

    Validates: Requirements 2.4, 3.6.
    """

    def test_call_sequence_and_argument_passing(self, tmp_path, token, temp_dirs):
        clone_dir, export_dir = temp_dirs
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()

        workflow = Workflow(
            name="my-workflow",
            repo_uri=REPO_URI,
            versions=[
                WorkflowVersion(
                    tag="v1", git_commit_id=COMMIT_ID, contexts=[]
                )
            ],
        )
        existing_patches = [
            PatchEntry(
                name="existing",
                path="patches/deadbeef.txt",
                md5sum="deadbeef",
                description="pre-existing",
            )
        ]
        config = _make_app_config(
            config_repo, patches=existing_patches, workflows=[workflow]
        )

        diffs = [_make_diff("main.nf"), _make_diff("conf/ica.config")]
        collected = [
            CollectedPatch(
                name="my-workflow_main",
                description="d",
                relative_path="main.nf",
                md5sum="aaa",
                is_new=True,
                was_skipped=False,
            )
        ]

        # A shared parent mock records the relative call order of every
        # collaborator so we can assert the orchestration sequence.
        with patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp",
            side_effect=[str(clone_dir), str(export_dir)],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit"
        ) as mock_clone, patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source"
        ) as mock_export, patch(
            "nf_ica_cli.handlers.collect_all_patches.generate_diffs",
            return_value=diffs,
        ) as mock_generate, patch(
            "nf_ica_cli.handlers.collect_all_patches.register_collected_patches",
            return_value=collected,
        ) as mock_register:
            handle_collect_all_patches(_make_args(), config, config_repo)

        # clone_at_commit receives repo uri, commit id, and the clone dir.
        mock_clone.assert_called_once_with(REPO_URI, COMMIT_ID, clone_dir)

        # export_pipeline_source receives the ids and the export dir.
        mock_export.assert_called_once_with(
            project_id=PROJECT_ID,
            pipeline_id=PIPELINE_ID,
            output_dir=export_dir,
        )

        # generate_diffs receives the clone dir and the export dir.
        mock_generate.assert_called_once_with(clone_dir, export_dir)

        # register_collected_patches receives the diffs, the derived workflow
        # identifier (from the matching workflow name), config_repo, and the
        # existing patches list.
        mock_register.assert_called_once()
        reg_kwargs = mock_register.call_args.kwargs
        assert reg_kwargs["diffs"] == diffs
        assert reg_kwargs["workflow_identifier"] == "my-workflow"
        assert reg_kwargs["config_repo"] == config_repo
        assert reg_kwargs["existing_patches"] == existing_patches

        # The overall call ordering is asserted separately in
        # test_call_order_is_clone_export_generate_register; here the argument
        # assertions above confirm the data threads correctly.

        # Cleanup: both temp dirs are removed after a successful run.
        assert not clone_dir.exists()
        assert not export_dir.exists()

    def test_call_order_is_clone_export_generate_register(
        self, tmp_path, token, temp_dirs
    ):
        """The four collaborators run in the documented order."""
        clone_dir, export_dir = temp_dirs
        config = _make_app_config(tmp_path)

        order = []

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp",
            side_effect=[str(clone_dir), str(export_dir)],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit",
            side_effect=lambda *a, **k: order.append("clone"),
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source",
            side_effect=lambda *a, **k: order.append("export"),
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.generate_diffs",
            side_effect=lambda *a, **k: (order.append("generate"), [_make_diff()])[1],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.register_collected_patches",
            side_effect=lambda *a, **k: (order.append("register"), [])[1],
        ):
            handle_collect_all_patches(_make_args(), config, tmp_path)

        assert order == ["clone", "export", "generate", "register"]


class TestCloneFailure:
    """A clone RuntimeError becomes a [GIT] SystemExit with cleanup.

    Validates: Requirements 2.2, 2.3.
    """

    def test_clone_failure_exits_git_and_cleans_up(self, tmp_path, token, temp_dirs):
        clone_dir, export_dir = temp_dirs
        config = _make_app_config(tmp_path)

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp",
            side_effect=[str(clone_dir), str(export_dir)],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit",
            side_effect=RuntimeError("could not resolve host"),
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source"
        ) as mock_export, patch(
            "nf_ica_cli.handlers.collect_all_patches.register_collected_patches"
        ) as mock_register:
            with pytest.raises(SystemExit) as exc_info:
                handle_collect_all_patches(_make_args(), config, tmp_path)

        error_msg = str(exc_info.value)
        assert "[GIT]" in error_msg
        # The message surfaces the repo uri and commit id (Req 2.2/2.3).
        assert REPO_URI in error_msg
        assert COMMIT_ID in error_msg

        # No downstream work happened after the clone failed.
        mock_export.assert_not_called()
        mock_register.assert_not_called()

        # Both temp dirs are still cleaned up on the error path (Req 2.4).
        assert not clone_dir.exists()
        assert not export_dir.exists()


class TestExportFailure:
    """An export RuntimeError becomes a SystemExit with cleanup.

    Validates: Requirements 3.6.
    """

    def test_export_failure_exits_and_cleans_up(self, tmp_path, token, temp_dirs):
        clone_dir, export_dir = temp_dirs
        config = _make_app_config(tmp_path)

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp",
            side_effect=[str(clone_dir), str(export_dir)],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit"
        ) as mock_clone, patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source",
            side_effect=RuntimeError(
                "Error: [ICA API] pipeline not found for project/pipeline."
            ),
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.generate_diffs"
        ) as mock_generate, patch(
            "nf_ica_cli.handlers.collect_all_patches.register_collected_patches"
        ) as mock_register:
            with pytest.raises(SystemExit) as exc_info:
                handle_collect_all_patches(_make_args(), config, tmp_path)

        # The exporter's error message is surfaced verbatim.
        assert "[ICA API]" in str(exc_info.value)

        # The clone ran, but nothing after the export failure did.
        mock_clone.assert_called_once()
        mock_generate.assert_not_called()
        mock_register.assert_not_called()

        # Both temp dirs are cleaned up on the export error path (Req 3.6).
        assert not clone_dir.exists()
        assert not export_dir.exists()


class TestNoDiffsPath:
    """No diffs -> a no-patches message to stdout, return, no registration.

    Validates: Requirements 6.3.
    """

    def test_no_diffs_prints_message_and_returns_without_register(
        self, tmp_path, token, temp_dirs, capsys
    ):
        clone_dir, export_dir = temp_dirs
        config = _make_app_config(tmp_path)

        with patch(
            "nf_ica_cli.handlers.collect_all_patches.tempfile.mkdtemp",
            side_effect=[str(clone_dir), str(export_dir)],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.clone_at_commit"
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.export_pipeline_source"
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.generate_diffs",
            return_value=[],
        ), patch(
            "nf_ica_cli.handlers.collect_all_patches.register_collected_patches"
        ) as mock_register:
            # Returns normally (exit status 0) rather than raising SystemExit.
            result = handle_collect_all_patches(_make_args(), config, tmp_path)

        assert result is None

        # A no-patches message went to stdout, not stderr.
        captured = capsys.readouterr()
        assert "No patches generated" in captured.out
        assert captured.err == ""

        # register_collected_patches is never called when there are no diffs.
        mock_register.assert_not_called()

        # Temp dirs are cleaned up even on the no-diffs early return.
        assert not clone_dir.exists()
        assert not export_dir.exists()
