"""Property-based tests for nf_ica_cli.diff_generator module.

Tests correctness properties from the collect-all-patches design document
using Hypothesis.
"""

from pathlib import Path
from typing import Dict, List

from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.diff_generator import collect_file_paths, generate_diffs


# --- Strategies ---

# A single path segment: a non-empty name that is not "." or ".." and does
# not contain path separators or NUL bytes (safe as a filesystem name).
_path_segment = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=8,
).filter(lambda s: s not in (".", ".."))

# A relative POSIX file path made of 1-4 segments (e.g. "conf/ica.config").
_relative_file_path = st.lists(_path_segment, min_size=1, max_size=4).map(
    lambda parts: "/".join(parts)
)

# Small file contents.
_file_content = st.text(max_size=64)

# A mapping of relative file path -> content, representing a directory tree.
_file_tree = st.dictionaries(
    keys=_relative_file_path,
    values=_file_content,
    min_size=0,
    max_size=8,
)


def _materialize_tree(root: Path, tree: Dict[str, str]) -> None:
    """Write the given {relative_path: content} mapping into ``root``.

    Generated path sets may contain conflicts (a name used both as a file and
    as a directory prefix). Such conflicting entries are skipped so the tree
    can always be materialized without raising.
    """
    for rel_path, content in tree.items():
        target = root / Path(rel_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            # A parent segment already exists as a file; skip this entry.
            continue
        if target.is_dir():
            # The path was already created as a directory by another entry.
            continue
        target.write_text(content)


def _git_tree_paths(tree: Dict[str, str]) -> Dict[str, str]:
    """Prefix every path in ``tree`` with ``.git/`` to place it under .git/."""
    return {f".git/{rel_path}": content for rel_path, content in tree.items()}


# --- Property 2: .git/ exclusion ---
# Feature: collect-all-patches, Property 2: For any pair of directories where both
# contain a .git/ subdirectory with arbitrary contents, the generated file path list
# SHALL never reference any path starting with ".git/".


class TestGitExclusion:
    """**Validates: Requirements 4.6**"""

    @given(
        source_tree=_file_tree,
        pipeline_tree=_file_tree,
        source_git_tree=_file_tree,
        pipeline_git_tree=_file_tree,
    )
    @settings(max_examples=100)
    def test_collect_file_paths_never_references_git_dir(
        self,
        source_tree: Dict[str, str],
        pipeline_tree: Dict[str, str],
        source_git_tree: Dict[str, str],
        pipeline_git_tree: Dict[str, str],
        tmp_path_factory,
    ) -> None:
        """No collected path starts with ``.git/`` even when .git/ has content.

        Feature: collect-all-patches, Property 2: .git/ exclusion
        """
        base = tmp_path_factory.mktemp("git_exclusion")
        source_dir = base / "source"
        pipeline_dir = base / "pipeline"
        source_dir.mkdir()
        pipeline_dir.mkdir()

        # Materialize the ordinary (non-.git) trees.
        _materialize_tree(source_dir, source_tree)
        _materialize_tree(pipeline_dir, pipeline_tree)

        # Materialize arbitrary contents under a .git/ subdirectory in both.
        _materialize_tree(source_dir, _git_tree_paths(source_git_tree))
        _materialize_tree(pipeline_dir, _git_tree_paths(pipeline_git_tree))

        result: List[str] = collect_file_paths(source_dir, pipeline_dir)

        # No collected path may reference the .git/ directory at the root.
        for rel_path in result:
            assert not rel_path.startswith(".git/"), (
                f"collected path '{rel_path}' references the excluded .git/ directory"
            )
            assert ".git" not in Path(rel_path).parts, (
                f"collected path '{rel_path}' contains a .git segment"
            )


# --- Property 1: Diff round-trip ---
# Feature: collect-all-patches, Property 1: For any pair of directories where at
# least one file differs, applying the generated concatenated patch to the source
# directory via `git apply` SHALL produce a directory tree whose file contents are
# identical to the pipeline directory (for all tracked files).

import shutil
import subprocess

from nf_ica_cli.diff_generator import generate_diffs


# Text content restricted to newline-terminated ASCII lines. `git diff --no-index`
# and `git apply` operate most predictably on well-formed text files, so the
# round-trip strategy uses line-oriented content rather than arbitrary bytes.
_line = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ",
    min_size=0,
    max_size=16,
)
_text_file_content = st.lists(_line, min_size=1, max_size=6).map(
    lambda lines: "\n".join(lines) + "\n"
)

# A directory tree of text files: {relative_path: content}.
_text_file_tree = st.dictionaries(
    keys=_relative_file_path,
    values=_text_file_content,
    min_size=0,
    max_size=6,
)


def _materialized_paths(root: Path, tree: Dict[str, str]) -> Dict[str, str]:
    """Materialize ``tree`` into ``root`` and return only the entries that were
    actually written (path-conflicting entries are skipped, mirroring
    ``_materialize_tree``)."""
    _materialize_tree(root, tree)
    written: Dict[str, str] = {}
    for rel_path in tree:
        target = root / Path(rel_path)
        if target.is_file():
            written[rel_path] = target.read_text()
    return written


def _read_all_files(root: Path) -> Dict[str, str]:
    """Read every non-.git file under ``root`` into {relative_posix_path: content}."""
    contents: Dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        contents[relative.as_posix()] = path.read_text()
    return contents


class TestDiffRoundTrip:
    """**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**"""

    @given(
        source_tree=_text_file_tree,
        pipeline_tree=_text_file_tree,
    )
    @settings(max_examples=100)
    def test_concatenated_patch_applied_reproduces_pipeline(
        self,
        source_tree: Dict[str, str],
        pipeline_tree: Dict[str, str],
        tmp_path_factory,
    ) -> None:
        """Applying the concatenated patch to a copy of source reproduces pipeline.

        Feature: collect-all-patches, Property 1: Diff round-trip
        """
        base = tmp_path_factory.mktemp("diff_round_trip")
        source_dir = base / "source"
        pipeline_dir = base / "pipeline"
        source_dir.mkdir()
        pipeline_dir.mkdir()

        # Materialize both trees, capturing exactly what landed on disk.
        _materialized_paths(source_dir, source_tree)
        _materialized_paths(pipeline_dir, pipeline_tree)

        # The union of files actually present on disk (excludes .git, which
        # neither tree contains here).
        expected_pipeline = _read_all_files(pipeline_dir)

        diffs = generate_diffs(source_dir, pipeline_dir)

        # Concatenate every FileDiff's content into a single patch, ordered as
        # generate_diffs returns them (alphabetical by relative_path).
        patch_text = "".join(diff.diff_content for diff in diffs)

        # Apply the patch to an independent copy of the source directory.
        applied_dir = base / "applied"
        shutil.copytree(source_dir, applied_dir)

        if patch_text:
            patch_file = base / "combined.patch"
            patch_file.write_text(patch_text)
            result = subprocess.run(
                ["git", "apply", str(patch_file)],
                cwd=str(applied_dir),
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                "git apply failed to apply the generated patch:\n"
                f"stderr: {result.stderr}\n"
                f"patch:\n{patch_text}"
            )

        # After applying, the copy's file contents must match the pipeline dir.
        applied_contents = _read_all_files(applied_dir)
        assert applied_contents == expected_pipeline, (
            "applying the concatenated patch to the source copy did not "
            "reproduce the pipeline directory contents"
        )


# --- Property 3: Alphabetical ordering of diffs ---
# Feature: collect-all-patches, Property 3: For any set of file differences between
# two directories, the concatenated patch output SHALL contain diff headers in
# strictly ascending alphabetical order by relative file path.


class TestAlphabeticalOrdering:
    """**Validates: Requirements 4.8**"""

    @given(
        source_tree=_file_tree,
        pipeline_tree=_file_tree,
    )
    @settings(max_examples=100)
    def test_generate_diffs_relative_paths_strictly_ascending(
        self,
        source_tree: Dict[str, str],
        pipeline_tree: Dict[str, str],
        tmp_path_factory,
    ) -> None:
        """FileDiff relative_path values are in strictly ascending order.

        Generates random source/pipeline file trees, runs ``generate_diffs``,
        and asserts the returned FileDiff list is ordered by ``relative_path``
        with no duplicates (strictly ascending), which guarantees the
        concatenated diff headers appear in ascending alphabetical order.

        Feature: collect-all-patches, Property 3: Alphabetical ordering of diffs
        """
        base = tmp_path_factory.mktemp("alpha_ordering")
        source_dir = base / "source"
        pipeline_dir = base / "pipeline"
        source_dir.mkdir()
        pipeline_dir.mkdir()

        _materialize_tree(source_dir, source_tree)
        _materialize_tree(pipeline_dir, pipeline_tree)

        diffs = generate_diffs(source_dir, pipeline_dir)

        relative_paths = [diff.relative_path for diff in diffs]

        # Strictly ascending: each path is less than the next (no duplicates,
        # no out-of-order entries).
        for earlier, later in zip(relative_paths, relative_paths[1:]):
            assert earlier < later, (
                "generate_diffs returned relative_path values that are not in "
                f"strictly ascending order: {earlier!r} is not < {later!r}; "
                f"full order was {relative_paths!r}"
            )
