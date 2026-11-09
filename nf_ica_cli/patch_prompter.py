"""Interactive patch prompting for the collect-all-patches subcommand.

Collects patch metadata (name, description) from the user for each generated
diff, suggesting a default name derived from the workflow identifier and the
relative file path. Also provides pure helpers for building those suggested
names so they can be property-tested in isolation.

This module provides ``suggest_patch_name`` (pure slug helper),
``validate_patch_name_available`` (format + availability check), and the
interactive ``prompt_for_patch_metadata`` flow that collects a name and
description from the user for each generated diff.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.validators import validate_patch_name

# Any character that is not permitted in a patch name is replaced with an
# underscore. Patch names must match [a-zA-Z0-9_-] (see validators.py).
_DISALLOWED_CHAR_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

# Collapse runs of consecutive underscores into a single underscore.
_MULTI_UNDERSCORE_PATTERN = re.compile(r"_+")


def _slugify_relative_path(relative_path: str) -> str:
    """Produce a patch-name slug from a relative file path.

    Slug rules:
        1. Remove the file extension (the final ``.<ext>`` suffix, if any).
        2. Replace path separators (``/`` and ``\\``) with underscores.
        3. Replace any character not matching ``[a-zA-Z0-9_-]`` with an
           underscore.
        4. Collapse consecutive underscores into a single underscore.

    Args:
        relative_path: File path relative to the directory root
            (e.g. ``"conf/ica.config"``).

    Returns:
        The slugified path (e.g. ``"conf_ica"``).
    """
    # (1) Strip the final file extension, if present. rsplit on "." keeps any
    # leading dots (e.g. a dotfile like ".gitignore" stays intact because it
    # has no extension segment to remove).
    dot_index = relative_path.rfind(".")
    slash_index = max(relative_path.rfind("/"), relative_path.rfind("\\"))
    # Only strip when the dot belongs to the final path segment (after the last
    # separator) and is not the leading character of that segment.
    if dot_index > slash_index + 1:
        relative_path = relative_path[:dot_index]

    # (2) Replace path separators with underscores.
    slug = relative_path.replace("/", "_").replace("\\", "_")

    # (3) Replace any remaining disallowed character with an underscore.
    slug = _DISALLOWED_CHAR_PATTERN.sub("_", slug)

    # (4) Collapse consecutive underscores into a single underscore.
    slug = _MULTI_UNDERSCORE_PATTERN.sub("_", slug)

    # Trim any leading/trailing underscore from the slug. This keeps the join
    # in suggest_patch_name (``<workflow_identifier>_<slug>``) from producing a
    # consecutive-underscore run at the prefix/slug boundary, without collapsing
    # across that boundary (which would eat the required separator).
    slug = slug.strip("_")

    return slug


def suggest_patch_name(
    workflow_identifier: str,
    relative_path: str,
) -> str:
    """Generate a suggested patch name for the user prompt.

    Pattern: ``<workflow_identifier>_<slug>``.

    The slug is derived from ``relative_path`` by removing the file extension,
    replacing path separators (``/`` and ``\\``) with underscores, replacing
    any character not matching ``[a-zA-Z0-9_-]`` with an underscore, and
    collapsing consecutive underscores into a single underscore.

    The suggested name is shown to the user, who can accept it (by pressing
    Enter) or override it with a custom name.

    Args:
        workflow_identifier: Identifier for the workflow the patch belongs to
            (e.g. ``"myworkflow"``).
        relative_path: File path relative to the directory root
            (e.g. ``"conf/ica.config"``).

    Returns:
        The suggested patch name (e.g. ``"myworkflow_conf_ica"``).
    """
    slug = _slugify_relative_path(relative_path)

    # Join as ``<workflow_identifier>_<slug>``. The workflow identifier is
    # preserved verbatim as a prefix followed by a single "_" separator, so the
    # result always begins with ``<workflow_identifier>_`` (Property 4, clause
    # c). We deliberately do NOT collapse underscores across this boundary:
    # doing so would eat the separator and break the prefix guarantee. The slug
    # itself has already had its internal runs collapsed and its edges trimmed
    # (see _slugify_relative_path), so joining never introduces a consecutive-
    # underscore run on the slug side.
    return f"{workflow_identifier}_{slug}"


def validate_patch_name_available(
    name: str,
    existing_names: Set[str],
) -> bool:
    """Check whether a patch name is both valid and not already registered.

    The format check is delegated to :func:`validators.validate_patch_name`,
    which enforces the ``[a-zA-Z0-9_-]+`` (non-empty) pattern and raises
    ``ValueError`` on an invalid name. Availability is checked against the set
    of names already present in the patch registry.

    On any failure, an error message is printed to stderr following the
    ``Error: [CATEGORY] message`` convention, and ``False`` is returned so the
    caller can re-prompt the user without proceeding to registration.

    Args:
        name: The candidate patch name provided by the user.
        existing_names: The set of patch names already present in the registry.

    Returns:
        ``True`` only when ``name`` is a valid patch name and is not already
        registered; ``False`` otherwise.
    """
    # Format validation (delegated). validate_patch_name raises ValueError on
    # an empty or malformed name; surface that message and reject.
    try:
        validate_patch_name(name)
    except ValueError as e:
        print(f"Error: [VALIDATION] {e}", file=sys.stderr)
        return False

    # Availability check against the existing registry.
    if name in existing_names:
        print(
            f"Error: [VALIDATION] Patch name already registered: '{name}'. "
            f"Each patch must have a unique name; choose a different name.",
            file=sys.stderr,
        )
        return False

    return True

@dataclass
class PatchPromptResult:
    """User-provided metadata for a collected patch.

    Attributes:
        name: The patch name the user accepted or provided. Empty when
            ``skip`` is ``True``.
        description: The non-empty description the user provided. Empty when
            ``skip`` is ``True``.
        skip: ``True`` if the user chose to skip registering this patch. Only
            offered when the patch content (MD5) already exists in the registry.
    """

    name: str
    description: str
    skip: bool


def prompt_for_patch_metadata(
    relative_path: str,
    patch_file_path: Path,
    existing_patches: List[PatchEntry],
    md5sum: str,
    workflow_identifier: str,
) -> PatchPromptResult:
    """Interactively prompt the user for a patch's name and description.

    Displays context for the patch being registered:

    * the relative file path that changed (Requirement 5.3),
    * a reference to the patch file at ``patches/<md5sum>.txt`` so the user can
      inspect its content (Requirement 5.3), and
    * a duplicate notification showing the existing patch name, the MD5 digest,
      and the ``patches/<md5>.txt`` path when the content already exists in the
      registry (Requirement 5.2).

    When the MD5 matches an existing entry, the user is offered the option to
    skip registration (Requirement 5.9). Otherwise the user is prompted for a
    name (defaulting to the suggested name when they press Enter with no input;
    re-prompting on an invalid or already-taken name — Requirements 5.5, 5.7,
    5.8) and a non-empty free-text description (Requirement 5.6).

    Args:
        relative_path: File path relative to the directory root that this patch
            modifies (e.g. ``"conf/ica.config"``).
        patch_file_path: Path to the temporary patch file whose content was
            hashed. Displayed for reference alongside the registry path.
        existing_patches: The patches already present in the registry, used to
            detect MD5 duplicates and enforce name uniqueness.
        md5sum: The MD5 hex digest of the patch content, used to build the
            ``patches/<md5>.txt`` reference and to detect duplicates.
        workflow_identifier: Identifier for the workflow the patch belongs to,
            used to build the suggested default name via
            :func:`suggest_patch_name`.

    Returns:
        A :class:`PatchPromptResult` capturing the user's choices.

    Raises:
        SystemExit: If standard input is not a TTY (non-interactive mode). An
            error message is printed to stderr first (Requirement 5.11).
    """
    # (Requirement 5.11) Interactive mode is required. Fail fast before any
    # prompting if stdin is not attached to a terminal.
    if not sys.stdin.isatty():
        print(
            "Error: [INTERACTIVE] Interactive mode is required to register "
            "patches, but standard input is not a TTY. Re-run this command in "
            "an interactive terminal.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    registry_path = f"patches/{md5sum}.txt"

    # (Requirement 5.3) Show the changed file and a reference to the patch file
    # so the user can inspect the content before naming it.
    print(f"\nPatch for: {relative_path}")
    print(f"  Patch file: {patch_file_path}")
    print(f"  Registry path: {registry_path}")

    # (Requirement 5.2) Detect an existing patch with the same content (MD5).
    duplicate_entry = next(
        (entry for entry in existing_patches if entry.md5sum == md5sum),
        None,
    )

    if duplicate_entry is not None:
        # (Requirement 5.2) Notify the user that this patch content already
        # exists, showing the existing name, the MD5, and the registry path.
        print(
            "  Note: this patch content already exists in the registry:\n"
            f"    name:   {duplicate_entry.name}\n"
            f"    md5:    {md5sum}\n"
            f"    path:   {registry_path}"
        )

        # (Requirement 5.9) Offer the option to skip registering the duplicate.
        while True:
            answer = input("  Skip this patch? [Y/n]: ").strip().lower()
            if answer in ("", "y", "yes"):
                return PatchPromptResult(name="", description="", skip=True)
            if answer in ("n", "no"):
                break
            print("  Please answer 'y' or 'n'.")

    # The set of names already taken, used for the availability check below.
    existing_names = {entry.name for entry in existing_patches}

    # Build the suggested default name from the workflow identifier and path.
    suggested_name = suggest_patch_name(workflow_identifier, relative_path)

    # (Requirements 5.5, 5.7, 5.8) Prompt for a name, defaulting to the
    # suggestion on an empty response, and re-prompting until the name is both
    # valid in format and not already registered.
    while True:
        raw_name = input(f"  Patch name [{suggested_name}]: ").strip()
        name = raw_name if raw_name else suggested_name

        if validate_patch_name_available(name, existing_names):
            break
        # validate_patch_name_available already printed the reason; loop again.

    # (Requirement 5.6) Prompt for a required, non-empty description.
    while True:
        description = input("  Description: ").strip()
        if description:
            break
        print("  Error: [VALIDATION] Description must not be empty.")

    return PatchPromptResult(name=name, description=description, skip=False)
