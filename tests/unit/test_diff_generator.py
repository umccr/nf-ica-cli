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

import hashlib
import shutil

from nf_ica_cli.diff_generator import (
    FileDiff,
    _normalize_diff_header,
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


class TestIndexLineStripped:
    """The volatile git ``index`` line is removed from normalized output.

    Stripping the ``index <hash>..<hash>[ <mode>]`` line lets identical
    logical patches content-address stably.
    """

    @staticmethod
    def _has_index_header(diff: str) -> bool:
        """True if any line is an unprefixed git ``index`` header line."""
        return any(line.startswith("index ") for line in diff.splitlines())

    def test_modified_file_has_no_index_line(self, dirs):
        """A modified-file diff (trailing-mode ``index`` form) drops the line."""
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
        assert "\nindex " not in diff
        assert not self._has_index_header(diff)
        # The remaining header and body lines survive.
        assert "diff --git a/conf/ica.config b/conf/ica.config" in diff
        assert "--- a/conf/ica.config" in diff
        assert "+++ b/conf/ica.config" in diff
        assert "-line2" in diff
        assert "+CHANGED" in diff

    def test_new_file_has_no_index_line(self, dirs):
        """A new-file diff (plain ``index a..b`` form) drops the line."""
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
        assert "\nindex " not in diff
        assert not self._has_index_header(diff)
        assert "--- /dev/null" in diff
        assert "+++ b/main.nf" in diff

    def test_body_line_beginning_with_index_is_preserved(self, dirs):
        """A hunk-body content line starting with 'index' must NOT be dropped.

        In a unified diff such a line is always prefixed by ``+``/``-``/space,
        so the column-0-anchored match can never remove it.
        """
        source_dir, pipeline_dir = dirs
        source_file = _write(source_dir, "notes.txt", "keep\n")
        pipeline_file = _write(
            pipeline_dir, "notes.txt", "keep\nindex 1234567..89abcde 100644\n"
        )

        diff = generate_single_file_diff(
            source_file=source_file,
            pipeline_file=pipeline_file,
            relative_path="notes.txt",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        assert diff is not None
        # The added content line (prefixed by '+') survives verbatim.
        assert "+index 1234567..89abcde 100644" in diff
        # No unprefixed git index header line remains.
        assert not self._has_index_header(diff)


class TestIndexLineDedup:
    """Two diffs differing only by git ``index`` blob hashes dedupe identically."""

    def test_new_file_differing_index_hashes_dedupe(self):
        """New-file diffs identical except for the ``index`` line normalize equal."""
        body = (
            "diff --git a/conf/icav2.config b/conf/icav2.config\n"
            "new file mode 100644\n"
            "{index}\n"
            "--- /dev/null\n"
            "+++ b/conf/icav2.config\n"
            "@@ -0,0 +1 @@\n"
            "+hello\n"
        )
        # Differing blob hashes AND differing hex width (8 vs 7).
        text1 = body.format(index="index 00000000..3edfd5f0")
        text2 = body.format(index="index 0000000..38a94c5")

        out1 = _normalize_diff_header(
            text1, "conf/icav2.config", is_new_file=True, is_deleted=False
        )
        out2 = _normalize_diff_header(
            text2, "conf/icav2.config", is_new_file=True, is_deleted=False
        )

        assert out1 == out2
        assert "\nindex " not in out1
        assert (
            hashlib.md5(out1.encode()).hexdigest()
            == hashlib.md5(out2.encode()).hexdigest()
        )

    def test_modified_file_trailing_mode_index_dedupe(self):
        """Modified-file ``index a..b <mode>`` form is stripped and dedupes."""
        body = (
            "diff --git a/conf/ica.config b/conf/ica.config\n"
            "{index}\n"
            "--- a/conf/ica.config\n"
            "+++ b/conf/ica.config\n"
            "@@ -1 +1 @@\n"
            "-before\n"
            "+after\n"
        )
        text1 = body.format(index="index abc1234..def5678 100644")
        text2 = body.format(index="index abcd123..def4567 100644")

        out1 = _normalize_diff_header(
            text1, "conf/ica.config", is_new_file=False, is_deleted=False
        )
        out2 = _normalize_diff_header(
            text2, "conf/ica.config", is_new_file=False, is_deleted=False
        )

        assert out1 == out2
        assert "\nindex " not in out1
        assert (
            hashlib.md5(out1.encode()).hexdigest()
            == hashlib.md5(out2.encode()).hexdigest()
        )


class TestStrippedDiffStillApplies:
    """A normalized diff with no ``index`` line still applies via ``git apply``."""

    def test_new_file_diff_applies(self, dirs, tmp_path):
        source_dir, pipeline_dir = dirs
        _write(pipeline_dir, "added.txt", "brand new\nsecond line\n")

        diff = generate_single_file_diff(
            source_file=None,
            pipeline_file=pipeline_dir / "added.txt",
            relative_path="added.txt",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )
        assert diff is not None
        assert not any(
            line.startswith("index ") for line in diff.splitlines()
        )

        apply_dir = tmp_path / "apply_new"
        apply_dir.mkdir()
        patch_file = apply_dir / "p.patch"
        patch_file.write_text(diff)
        result = subprocess.run(
            ["git", "apply", str(patch_file)],
            cwd=str(apply_dir),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (apply_dir / "added.txt").read_text() == "brand new\nsecond line\n"

    def test_modified_file_diff_applies(self, dirs, tmp_path):
        source_dir, pipeline_dir = dirs
        _write(source_dir, "edit.txt", "line1\nline2\nline3\n")
        _write(pipeline_dir, "edit.txt", "line1\nCHANGED\nline3\n")

        diff = generate_single_file_diff(
            source_file=source_dir / "edit.txt",
            pipeline_file=pipeline_dir / "edit.txt",
            relative_path="edit.txt",
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )
        assert diff is not None
        assert not any(
            line.startswith("index ") for line in diff.splitlines()
        )

        apply_dir = tmp_path / "apply_mod"
        apply_dir.mkdir()
        shutil.copy(source_dir / "edit.txt", apply_dir / "edit.txt")
        patch_file = apply_dir / "p.patch"
        patch_file.write_text(diff)
        result = subprocess.run(
            ["git", "apply", str(patch_file)],
            cwd=str(apply_dir),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (apply_dir / "edit.txt").read_text() == "line1\nCHANGED\nline3\n"
