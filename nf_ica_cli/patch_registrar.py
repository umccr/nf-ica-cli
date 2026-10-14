"""Patch registrar for the collect-all-patches subcommand.

Takes the unified diffs produced by :mod:`nf_ica_cli.diff_generator`, prompts
the user for a name and description for each one (via
:mod:`nf_ica_cli.patch_prompter`), and registers the non-skipped patches into
the content-addressed patch store using :mod:`nf_ica_cli.patches`.

Each diff is written to a temporary file so its MD5 digest can be computed and
so it can be handed to :func:`nf_ica_cli.patches.register_patch`, which either
copies the content to ``patches/<md5>.txt`` (new content) or reuses the
existing file (matching MD5). Registered entries are appended to
``config/patches.yaml`` via :mod:`nf_ica_cli.yaml_io`, matching the convention
used by the ``register-patch`` handler.
"""

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from nf_ica_cli.diff_generator import FileDiff
from nf_ica_cli.patch_prompter import prompt_for_patch_metadata
from nf_ica_cli.patches import PatchEntry, compute_md5, register_patch
from nf_ica_cli.yaml_io import load_yaml, save_yaml


@dataclass
class CollectedPatch:
    """Result of registering one collected patch.

    Attributes:
        name: User-provided patch name. Empty when the patch was skipped.
        description: User-provided description. Empty when the patch was skipped.
        relative_path: Original file path that was diffed.
        md5sum: MD5 hex digest of the patch content.
        is_new: ``True`` when the MD5 did not already exist in the registry (a
            new patch file was written); ``False`` when the content was reused.
        was_skipped: ``True`` when the user chose to skip registering this patch.
    """

    name: str
    description: str
    relative_path: str
    md5sum: str
    is_new: bool
    was_skipped: bool


def register_collected_patches(
    diffs: List[FileDiff],
    workflow_identifier: str,
    config_repo: Path,
    existing_patches: List[PatchEntry],
) -> List[CollectedPatch]:
    """Register collected diffs as patches with interactive user prompting.

    For each :class:`FileDiff`:

    1. Write the diff content to a temporary file.
    2. Compute its MD5 via :func:`nf_ica_cli.patches.compute_md5`.
    3. Detect whether that MD5 already exists in ``existing_patches``
       (Requirement 5.2).
    4. Prompt the user for a name and description via
       :func:`nf_ica_cli.patch_prompter.prompt_for_patch_metadata`, passing the
       ``workflow_identifier`` through for the suggested name.
    5. If the user skips (only offered for MD5 duplicates), record the skip and
       move on without registering (Requirement 5.9).
    6. Otherwise call :func:`nf_ica_cli.patches.register_patch` to store the
       file (only writing new content — Requirement 5.1) and append the entry
       to ``config/patches.yaml`` (Requirement 5.10).

    When a temporary patch file cannot be accessed (missing or not writable),
    an error identifying the file path is reported to stderr and that patch is
    skipped (Requirement 5.12), continuing with the remaining diffs.

    Args:
        diffs: The unified diffs to register, in the order they should be
            presented to the user.
        workflow_identifier: Identifier for the workflow the patches belong to,
            used to build suggested names.
        config_repo: Path to the configuration repository root. ``patches.yaml``
            lives at ``config_repo/config/patches.yaml`` and patch files at
            ``config_repo/patches/<md5>.txt``.
        existing_patches: Patches already present in the registry. Used to
            detect MD5 duplicates and enforce name uniqueness. Newly registered
            patches are appended to this list as processing proceeds so later
            diffs see them.

    Returns:
        A list of :class:`CollectedPatch` results, one per processed diff that
        was not skipped due to a file-access error, in input order.
    """
    patches_path = config_repo / "config" / "patches.yaml"

    # Work on a mutable copy so newly registered patches are visible to later
    # diffs (for duplicate/name-collision detection) without mutating the
    # caller's list unexpectedly.
    registry: List[PatchEntry] = list(existing_patches)

    results: List[CollectedPatch] = []

    for diff in diffs:
        # (1) Write the diff content to a temporary file so it can be hashed
        # and handed to register_patch.
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".txt",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(diff.diff_content)
                temp_patch_path = Path(tmp.name)
        except OSError as e:
            # (Requirement 5.12) Could not create/write the temp patch file.
            print(
                f"Error: [FILE ACCESS] Could not write patch file for "
                f"'{diff.relative_path}': {e}. Skipping this patch.",
                file=sys.stderr,
            )
            continue

        try:
            # (2) Verify the temp file is present and readable/writable, then
            # compute its MD5. compute_md5 raises FileNotFoundError /
            # PermissionError if the file is missing or unreadable.
            if not temp_patch_path.exists():
                raise FileNotFoundError(
                    f"Error: [FILE ACCESS] Patch file not found: "
                    f"'{temp_patch_path}'."
                )

            md5sum = compute_md5(temp_patch_path)

            # (3) Detect an existing registry entry with the same content.
            md5_exists = any(entry.md5sum == md5sum for entry in registry)

            # (4) Prompt the user for name/description (or a skip choice).
            prompt_result = prompt_for_patch_metadata(
                relative_path=diff.relative_path,
                patch_file_path=temp_patch_path,
                existing_patches=registry,
                md5sum=md5sum,
                workflow_identifier=workflow_identifier,
            )

            # (5) User chose to skip (only offered for MD5 duplicates).
            if prompt_result.skip:
                results.append(
                    CollectedPatch(
                        name="",
                        description="",
                        relative_path=diff.relative_path,
                        md5sum=md5sum,
                        is_new=False,
                        was_skipped=True,
                    )
                )
                continue

            # (6) Register the patch: copies content to patches/<md5>.txt only
            # when the MD5 is new (Requirement 5.1), reuses otherwise.
            try:
                patch_entry = register_patch(
                    config_repo=config_repo,
                    source_file=temp_patch_path,
                    name=prompt_result.name,
                    description=prompt_result.description,
                    existing_patches=registry,
                )
            except (ValueError, FileNotFoundError, PermissionError) as e:
                # (Requirement 5.12) File access failure during registration:
                # report the path and skip this patch.
                print(str(e), file=sys.stderr)
                continue

            # Append the entry to patches.yaml (Requirement 5.10).
            _append_patch_entry(patches_path, patch_entry)

            # Make the new entry visible to subsequent diffs.
            registry.append(patch_entry)

            results.append(
                CollectedPatch(
                    name=patch_entry.name,
                    description=patch_entry.description,
                    relative_path=diff.relative_path,
                    md5sum=md5sum,
                    is_new=not md5_exists,
                    was_skipped=False,
                )
            )
        finally:
            # Best-effort cleanup of the temporary patch file.
            try:
                temp_patch_path.unlink()
            except OSError:
                pass

    return results


def _append_patch_entry(patches_path: Path, patch_entry: PatchEntry) -> None:
    """Append a registered patch entry to ``patches.yaml``.

    Loads the existing YAML document (preserving comments/formatting), ensures
    a ``patches`` list exists, appends the new entry's ``name``, ``path``,
    ``md5sum`` and ``description`` fields, and writes the document back.

    Args:
        patches_path: Path to ``config/patches.yaml``.
        patch_entry: The registered patch entry to append.
    """
    if patches_path.exists():
        patches_data = load_yaml(patches_path)
    else:
        patches_data = {}

    if patches_data is None:
        patches_data = {}
    if "patches" not in patches_data or patches_data["patches"] is None:
        patches_data["patches"] = []

    patches_data["patches"].append(
        {
            "name": patch_entry.name,
            "path": patch_entry.path,
            "md5sum": patch_entry.md5sum,
            "description": patch_entry.description,
        }
    )

    save_yaml(patches_path, patches_data)
