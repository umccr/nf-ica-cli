"""Diff generation for the collect-all-patches subcommand.

Compares a source repository directory against an ICA pipeline source
directory and produces unified diffs (compatible with ``git apply``) for
each file that differs between the two trees.

Diffs are generated with ``git diff --no-index`` so that the output matches
the existing nf-ica patch application infrastructure.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Directory name that must be excluded from diff comparison.
_GIT_DIR_NAME = ".git"

# Matches the volatile git ``index`` header line, e.g.
# ``index 00000000..3edfd5f0`` (new/deleted file) or
# ``index 422c2b7..0f7bc76 100644`` (modified file, trailing octal mode).
# Anchored at column 0 so hunk-body lines beginning with the word "index"
# (always prefixed by ``+``/``-``/space in a unified diff) can never match.
_GIT_INDEX_LINE_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+( [0-7]+)?$")

# Matches ``old mode 100755`` / ``new mode 100644`` permission-change headers.
_MODE_CHANGE_LINE_RE = re.compile(r"^(old|new) mode [0-7]+$")


def _is_uploaded_by_wrapica(path: Path, root: Path) -> bool:
    """Return True if wrapica would upload ``path`` when building the pipeline.

    Mirrors the prefilter applied by
    ``wrapica.project_pipelines.create_nextflow_pipeline_from_zip`` when it
    collects the files to attach to an ICA pipeline. wrapica skips:

    * files whose top-level path component (relative to the pipeline root)
      starts with ``.`` (e.g. ``.github/...``, ``.gitignore``,
      ``.gitattributes``), and
    * empty files (zero bytes).

    These files are therefore never present in the exported ICA pipeline
    source, so including them on the source side only produces spurious
    "delete" diffs. Excluding them here keeps the source file set aligned with
    what wrapica actually uploaded.

    Note: wrapica does *not* exclude test directories (``tests/``, ``test/``)
    or hidden files nested below the top level, so those are intentionally
    left in place here to match wrapica's behaviour.

    Args:
        path: The file being considered (must be a regular file).
        root: The directory root the path is relative to.

    Returns:
        True if wrapica would have uploaded the file, False otherwise.
    """
    relative = path.relative_to(root)

    # Skip files whose top-level directory/name starts with a dot.
    if relative.parts and relative.parts[0].startswith("."):
        return False

    # Skip empty files.
    if path.stat().st_size == 0:
        return False

    return True


@dataclass
class FileDiff:
    """Represents a unified diff for a single file.

    Attributes:
        relative_path: Path relative to the directory root (e.g. "conf/ica.config").
        diff_content: Full unified diff text compatible with ``git apply``.
        is_new_file: True if the file exists only in the pipeline source.
        is_deleted: True if the file exists only in the source repo.
    """

    relative_path: str
    diff_content: str
    is_new_file: bool
    is_deleted: bool


def _collect_relative_files(root: Path, apply_wrapica_filter: bool = False) -> List[str]:
    """Collect POSIX-style relative file paths under ``root``.

    Any file located under a ``.git/`` directory (at any depth) is excluded.

    When ``apply_wrapica_filter`` is True, additionally excludes files that
    wrapica would not upload to the ICA pipeline (top-level dotfiles and empty
    files) via :func:`_is_uploaded_by_wrapica`. This is used for the source
    (clone) side so its file set matches what wrapica actually deployed,
    avoiding spurious "delete" diffs for files that never reach ICA.

    Args:
        root: Directory to walk.
        apply_wrapica_filter: When True, drop files wrapica would not upload.

    Returns:
        List of relative file paths using forward slashes. Empty if the
        directory does not exist.
    """
    if not root.is_dir():
        return []

    relative_paths: List[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        # Exclude anything under a .git/ directory at any depth.
        if _GIT_DIR_NAME in relative.parts:
            continue
        # Exclude files wrapica would not have uploaded (source side only).
        if apply_wrapica_filter and not _is_uploaded_by_wrapica(path, root):
            continue
        relative_paths.append(relative.as_posix())
    return relative_paths


def collect_file_paths(
    source_dir: Path,
    pipeline_dir: Path,
) -> List[str]:
    """Collect the union of all relative file paths from both directories.

    Excludes ``.git/`` directory contents from both sides. On the source side,
    additionally excludes files wrapica would not upload to ICA (top-level
    dotfiles and empty files), so they don't surface as spurious "delete"
    diffs against the pipeline export.

    Args:
        source_dir: Path to the cloned source repository.
        pipeline_dir: Path to the exported ICA pipeline source.

    Returns:
        Sorted list of unique relative file paths (forward-slash separated).
    """
    # Apply wrapica's upload prefilter to the source (clone) side so files
    # wrapica never uploads (top-level dotfiles, empty files) don't appear as
    # spurious "delete" diffs. The pipeline export side is taken as-is.
    paths = set(_collect_relative_files(source_dir, apply_wrapica_filter=True))
    paths.update(_collect_relative_files(pipeline_dir))
    return sorted(paths)


def _normalize_diff_header(
    diff_text: str,
    relative_path: str,
    is_new_file: bool,
    is_deleted: bool,
) -> str:
    """Rewrite ``git diff --no-index`` header paths to relative ``a/``/``b/`` form.

    ``git diff --no-index`` labels the diff with the (possibly absolute) paths
    it was given. This rewrites the ``diff --git``, ``---`` and ``+++`` header
    lines so the patch references ``a/<relative_path>`` and ``b/<relative_path>``,
    matching the existing nf-ica patch format and keeping the output compatible
    with ``git apply``. ``/dev/null`` markers for new/deleted files are preserved.

    The volatile git ``index <hash>..<hash>[ <mode>]`` line is also stripped
    from the normalized output entirely, for stable content-addressing: the
    blob hashes git emits vary between otherwise-identical patches (and even in
    hex width), so dropping the line lets identical logical patches produce
    identical normalized text and therefore identical MD5s. ``git apply`` does
    not require the ``index`` line, so removing it is safe for the round-trip.

    Args:
        diff_text: Raw unified diff produced by ``git diff --no-index``.
        relative_path: File path relative to the directory roots.
        is_new_file: True if the file exists only in the pipeline source.
        is_deleted: True if the file exists only in the source repo.

    Returns:
        The diff text with normalized header path references.
    """
    a_ref = "/dev/null" if is_new_file else f"a/{relative_path}"
    b_ref = "/dev/null" if is_deleted else f"b/{relative_path}"

    normalized_lines: List[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            normalized_lines.append(
                f"diff --git a/{relative_path} b/{relative_path}"
            )
        elif _GIT_INDEX_LINE_RE.match(line):
            # Drop the volatile ``index <hash>..<hash>[ <mode>]`` line so
            # identical logical patches content-address stably.
            continue
        elif line.startswith("--- "):
            normalized_lines.append(f"--- {a_ref}")
        elif line.startswith("+++ "):
            normalized_lines.append(f"+++ {b_ref}")
        else:
            normalized_lines.append(line)

    # Preserve the trailing newline behaviour of the original diff.
    normalized = "\n".join(normalized_lines)
    if diff_text.endswith("\n"):
        normalized += "\n"
    return normalized


def generate_single_file_diff(
    source_file: Optional[Path],
    pipeline_file: Optional[Path],
    relative_path: str,
    source_dir: Path,
    pipeline_dir: Path,
) -> Optional[str]:
    """Generate a unified diff for a single file pair using ``git diff --no-index``.

    Handles three cases:

    * **Modified** – both ``source_file`` and ``pipeline_file`` are provided.
    * **New file** – ``source_file`` is ``None``; the source side is diffed
      against ``/dev/null`` so the patch represents a file addition.
    * **Deleted file** – ``pipeline_file`` is ``None``; the pipeline side is
      diffed against ``/dev/null`` so the patch represents a file deletion.

    The resulting diff header references ``a/<relative_path>`` and
    ``b/<relative_path>`` (or ``/dev/null`` for the added/deleted side),
    matching the existing nf-ica patch format.

    Args:
        source_file: Path to the file in the source repository, or ``None``
            when the file does not exist in the source (new file).
        pipeline_file: Path to the file in the pipeline export, or ``None``
            when the file does not exist in the pipeline (deleted file).
        relative_path: File path relative to the directory roots, used for the
            ``a/`` and ``b/`` header prefixes.
        source_dir: Root of the cloned source repository (used for error context).
        pipeline_dir: Root of the exported pipeline source (used for error context).

    Returns:
        The normalized unified diff text, or ``None`` when the files are
        identical (``git diff`` exit code 0).

    Raises:
        RuntimeError: If ``git diff --no-index`` exits with a code other than
            0 (identical) or 1 (differences found).
    """
    is_new_file = source_file is None
    is_deleted = pipeline_file is None

    a_path = "/dev/null" if source_file is None else str(source_file)
    b_path = "/dev/null" if pipeline_file is None else str(pipeline_file)

    cmd = ["git", "diff", "--no-index", a_path, b_path]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        # Files are identical - no patch to produce.
        return None

    if result.returncode != 1:
        raise RuntimeError(
            f"Failed to diff file pair for '{relative_path}' "
            f"(source_dir='{source_dir}', pipeline_dir='{pipeline_dir}'): "
            f"command {cmd!r} exited with code {result.returncode}: "
            f"{result.stderr.strip()}"
        )

    # Exit code 1 => differences found.
    normalized = _normalize_diff_header(
        result.stdout,
        relative_path,
        is_new_file=is_new_file,
        is_deleted=is_deleted,
    )

    # ICA does not preserve file permissions, so exec-bit differences are
    # noise. Drop ``old mode``/``new mode`` lines, and skip the file entirely
    # if nothing but the mode changed.
    normalized = _strip_mode_change_lines(normalized)
    if not is_new_file and not is_deleted and not _has_content_changes(normalized):
        return None
    return normalized


def _strip_mode_change_lines(diff_text: str) -> str:
    """Remove ``old mode <m>`` / ``new mode <m>`` header lines from a diff."""
    lines = [ln for ln in diff_text.splitlines() if not _MODE_CHANGE_LINE_RE.match(ln)]
    out = "\n".join(lines)
    if diff_text.endswith("\n"):
        out += "\n"
    return out


def _has_content_changes(diff_text: str) -> bool:
    """Return True if the diff contains text hunks or a binary change."""
    return any(
        ln.startswith("--- ")
        or ln.startswith("Binary files ")
        or ln.startswith("GIT binary patch")
        for ln in diff_text.splitlines()
    )


def generate_diffs(
    source_dir: Path,
    pipeline_dir: Path,
) -> List[FileDiff]:
    """Generate unified diffs between source and pipeline directories.

    Collects the union of relative file paths from both directories
    (excluding ``.git/`` contents), diffs each corresponding file pair, and
    builds a :class:`FileDiff` for every pair whose content differs. Files
    with identical content produce no ``FileDiff``.

    For each relative path, the file's presence in each directory determines:

    * ``is_new_file`` – the file exists only in ``pipeline_dir``.
    * ``is_deleted`` – the file exists only in ``source_dir``.

    The matching ``Optional[Path]`` arguments (``None`` for the missing side)
    are passed to :func:`generate_single_file_diff`.

    Args:
        source_dir: Path to the cloned source repository.
        pipeline_dir: Path to the exported ICA pipeline source.

    Returns:
        List of :class:`FileDiff` objects ordered alphabetically by
        ``relative_path``. Empty list if the directories are identical
        (no differing files).

    Raises:
        RuntimeError: Propagated from :func:`generate_single_file_diff` when a
            file comparison fails unexpectedly.
    """
    # collect_file_paths returns a sorted (alphabetical) list of relative
    # paths, so iterating in order yields FileDiffs ordered by relative_path.
    diffs: List[FileDiff] = []
    for relative_path in collect_file_paths(source_dir, pipeline_dir):
        source_file = source_dir / relative_path
        pipeline_file = pipeline_dir / relative_path

        source_exists = source_file.is_file()
        pipeline_exists = pipeline_file.is_file()

        is_new_file = pipeline_exists and not source_exists
        is_deleted = source_exists and not pipeline_exists

        diff_content = generate_single_file_diff(
            source_file=source_file if source_exists else None,
            pipeline_file=pipeline_file if pipeline_exists else None,
            relative_path=relative_path,
            source_dir=source_dir,
            pipeline_dir=pipeline_dir,
        )

        # Identical content yields None - no FileDiff produced.
        if diff_content is None:
            continue

        diffs.append(
            FileDiff(
                relative_path=relative_path,
                diff_content=diff_content,
                is_new_file=is_new_file,
                is_deleted=is_deleted,
            )
        )

    return diffs
