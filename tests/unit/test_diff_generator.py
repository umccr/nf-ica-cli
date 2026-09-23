"""Unit tests for nf_ica_cli.diff_generator module.

Covers diff generation edge cases for the collect-all-patches subcommand:
new-file, deleted-file, modified-file, identical-file, and the
``git diff --no-index`` error path (exit code other than 0 or 1).

The new/deleted/modified/identical cases exercise the real ``git diff``
binary against on-disk temp directories so the produced patch text is
verified end-to-end. The error path mocks ``subprocess.run`` to force an
unexpected exit code (2), since that condition cannot be reproduced
deterministically with real inputs.

Validates: Requirements 4.2, 4.3, 4.4, 4.7
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.diff_generator import (
    FileDiff,
    generate_diffs,
    generate_single_file_diff,
)


@pytest.fixture
def dirs(tmp_path):
    """Create empty ``source`` and ``pipeline`` directories under tmp_path."""
    source_dir = tmp_path / "source"
    pipeline_dir = tmp_path / "pipeline"
    source_dir.mkdir()
    pipeline_dir.mkdir()
    return source_dir, pipeline_dir


def _write(root: Path, relative_path: str, content: str) -> Path:
    """Write ``content`` to ``root/relative_path`` creating parents."""
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    """Helper to build a CompletedProcess result for mocking."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestGenerateSingleFileDiffModified:
    """A file present in both directories with differing content.

    Validates: Requirements 4.4 (differing files produce a diff).
    """

    def test_modified_file_produces_diff(self, dirs):
        source_dir, pipeline_dir = dirs
        source_file = _write(source_dir, "conf/ica.config", "line1\nline2\n")
        pipeline_file = _write(pipeline_dir, "conf/ica.config", "line1\nCHANGED\n")

        diff = generate_single_file_diff(
            source_file=source_file,
            pipeline_file=pipeline_file,
            relative_path="conf/ica.config",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        assert diff is not None
        # Header is normalized to a/<rel> b/<rel> form.
        assert "diff --git a/conf/ica.config b/conf/ica.config" in diff
        assert "--- a/conf/ica.config" in diff
        assert "+++ b/conf/ica.config" in diff
        assert "-line2" in diff
        assert "+CHANGED" in diff


class TestGenerateSingleFileDiffNewFile:
    """A file present only in the pipeline (new file addition).

    Validates: Requirements 4.2.
    """

    def test_new_file_diffs_against_dev_null(self, dirs):
        source_dir, pipeline_dir = dirs
        pipeline_file = _write(pipeline_dir, "main.nf", "process foo {}\n")

        diff = generate_single_file_diff(
            source_file=None,
            pipeline_file=pipeline_file,
            relative_path="main.nf",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        assert diff is not None
        assert "diff --git a/main.nf b/main.nf" in diff
        # The added side references the file; the missing source side is /dev/null.
        assert "--- /dev/null" in diff
        assert "+++ b/main.nf" in diff
        assert "+process foo {}" in diff


class TestGenerateSingleFileDiffDeletedFile:
    """A file present only in the source (deletion).

    Validates: Requirements 4.3.
    """

    def test_deleted_file_diffs_against_dev_null(self, dirs):
        source_dir, pipeline_dir = dirs
        source_file = _write(source_dir, "old.nf", "legacy content\n")

        diff = generate_single_file_diff(
            source_file=source_file,
            pipeline_file=None,
            relative_path="old.nf",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        assert diff is not None
        assert "diff --git a/old.nf b/old.nf" in diff
        assert "--- a/old.nf" in diff
        # The deleted side is /dev/null.
        assert "+++ /dev/null" in diff
        assert "-legacy content" in diff


class TestGenerateSingleFileDiffIdentical:
    """A file present in both directories with identical content.

    Validates: Requirements 4.4 (identical files produce no diff).
    """

    def test_identical_file_returns_none(self, dirs):
        source_dir, pipeline_dir = dirs
        source_file = _write(source_dir, "nextflow.config", "same\n")
        pipeline_file = _write(pipeline_dir, "nextflow.config", "same\n")

        diff = generate_single_file_diff(
            source_file=source_file,
            pipeline_file=pipeline_file,
            relative_path="nextflow.config",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        assert diff is None


class TestGenerateSingleFileDiffErrorPath:
    """``git diff --no-index`` exits with a code other than 0 or 1.

    Validates: Requirements 4.7.
    """

    def test_exit_code_two_raises_runtime_error(self, dirs):
        source_dir, pipeline_dir = dirs

        with patch(
            "nf_ica_cli.diff_generator.subprocess.run"
        ) as mock_run:
            mock_run.return_value = _make_completed_process(
                returncode=2,
                stderr="fatal: something went wrong",
            )

            with pytest.raises(RuntimeError) as exc_info:
                generate_single_file_diff(
                    source_file=source_dir / "a.txt",
                    pipeline_file=pipeline_dir / "a.txt",
                    relative_path="a.txt",
                    source_dir=source_dir,
                    pipeline_dir=pipeline_dir,
                )

        error_msg = str(exc_info.value)
        # The error identifies the failing file pair and the exit code.
        assert "a.txt" in error_msg
        assert "exited with code 2" in error_msg
        assert "fatal: something went wrong" in error_msg


class TestGenerateDiffs:
    """End-to-end orchestration over a directory pair."""

    def test_mixed_tree_produces_ordered_diffs(self, dirs):
        """New, deleted, modified, and identical files are handled together.

        Validates: Requirements 4.2, 4.3, 4.4.
        """
        source_dir, pipeline_dir = dirs

        # Identical file -> no diff.
        _write(source_dir, "same.txt", "unchanged\n")
        _write(pipeline_dir, "same.txt", "unchanged\n")
        # Modified file -> diff.
        _write(source_dir, "b_modified.txt", "before\n")
        _write(pipeline_dir, "b_modified.txt", "after\n")
        # Source-only -> deletion diff.
        _write(source_dir, "a_deleted.txt", "gone\n")
        # Pipeline-only -> new-file diff.
        _write(pipeline_dir, "c_new.txt", "brand new\n")

        diffs = generate_diffs(source_dir, pipeline_dir)

        by_path = {d.relative_path: d for d in diffs}

        # Identical file produced no FileDiff.
        assert "same.txt" not in by_path

        # Deleted file.
        assert by_path["a_deleted.txt"].is_deleted is True
        assert by_path["a_deleted.txt"].is_new_file is False

        # Modified file.
        assert by_path["b_modified.txt"].is_deleted is False
        assert by_path["b_modified.txt"].is_new_file is False

        # New file.
        assert by_path["c_new.txt"].is_new_file is True
        assert by_path["c_new.txt"].is_deleted is False

        # Ordered alphabetically by relative_path.
        relative_paths = [d.relative_path for d in diffs]
        assert relative_paths == sorted(relative_paths)
        assert relative_paths == ["a_deleted.txt", "b_modified.txt", "c_new.txt"]

    def test_identical_directories_return_empty_list(self, dirs):
        """Directories with identical content produce no diffs.

        Validates: Requirements 4.4.
        """
        source_dir, pipeline_dir = dirs
        _write(source_dir, "main.nf", "identical\n")
        _write(pipeline_dir, "main.nf", "identical\n")

        assert generate_diffs(source_dir, pipeline_dir) == []

    def test_error_path_propagates_from_generate_diffs(self, dirs):
        """An unexpected git exit code surfaces as RuntimeError identifying the file.

        Validates: Requirements 4.7.
        """
        source_dir, pipeline_dir = dirs
        _write(source_dir, "boom.txt", "x\n")
        _write(pipeline_dir, "boom.txt", "y\n")

        with patch(
            "nf_ica_cli.diff_generator.subprocess.run"
        ) as mock_run:
            mock_run.return_value = _make_completed_process(
                returncode=2,
                stderr="fatal: diff blew up",
            )

            with pytest.raises(RuntimeError, match="boom.txt"):
                generate_diffs(source_dir, pipeline_dir)
