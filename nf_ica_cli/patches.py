"""Patch manager for nf-ica CLI.

Handles content-addressed patch storage, registration, and application.
Patches are stored as `patches/<md5sum>.txt` in the config repo and
referenced by name in patches.yaml.
"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from nf_ica_cli.validators import validate_patch_name


@dataclass
class PatchEntry:
    """A registered patch entry in patches.yaml."""

    name: str
    path: str
    md5sum: str
    description: str


def compute_md5(file_path: Path) -> str:
    """Compute MD5 hex digest of file contents.

    Args:
        file_path: Path to the file to hash.

    Returns:
        Lowercase hexadecimal MD5 digest string.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If the file is not readable.
    """
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def register_patch(
    config_repo: Path,
    source_file: Path,
    name: str,
    description: str,
    existing_patches: List[PatchEntry],
) -> PatchEntry:
    """Register a patch file by content hash.

    Workflow:
    1. Validate patch name format
    2. Check for name collision in existing_patches
    3. Compute MD5 of source file
    4. If MD5 doesn't match any existing entry, copy file to patches/<md5sum>.txt
    5. If MD5 matches existing entry, reuse existing path (skip copy)
    6. Return PatchEntry with name, path, md5sum, description

    Args:
        config_repo: Path to the configuration repository root.
        source_file: Path to the patch file to register.
        name: Unique name for the patch (alphanumeric, hyphens, underscores).
        description: Human-readable description of the patch.
        existing_patches: List of already-registered PatchEntry objects.

    Returns:
        A new PatchEntry for the registered patch.

    Raises:
        ValueError: If the patch name is invalid or already registered.
        FileNotFoundError: If the source file does not exist.
        PermissionError: If the source file is not readable.
    """
    # 1. Validate patch name format
    validate_patch_name(name)

    # 2. Check for name collision
    for entry in existing_patches:
        if entry.name == name:
            raise ValueError(
                f"Error: [VALIDATION] Patch name already registered: '{name}'. "
                f"Each patch must have a unique name."
            )

    # 3. Verify source file is accessible
    if not source_file.exists():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Patch file not found: '{source_file}'. "
            f"Verify the file path is correct and the file exists."
        )

    if not source_file.is_file():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Path is not a file: '{source_file}'."
        )

    # 4. Compute MD5 of source file
    md5sum = compute_md5(source_file)
    patch_relative_path = f"patches/{md5sum}.txt"
    patch_dest = config_repo / patch_relative_path

    # 5. Check if content already exists (same MD5)
    md5_exists = any(entry.md5sum == md5sum for entry in existing_patches)

    if not md5_exists:
        # Copy file to patches/<md5sum>.txt
        patch_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, patch_dest)

    # 6. Return new PatchEntry
    return PatchEntry(
        name=name,
        path=patch_relative_path,
        md5sum=md5sum,
        description=description,
    )


def apply_patches(
    repo_dir: Path,
    patch_names: List[str],
    patches_registry: List[PatchEntry],
    config_repo: Path,
) -> None:
    """Apply patches in order to a cloned repository.

    For each patch name in the list:
    1. Find matching PatchEntry in patches_registry
    2. Resolve full path: config_repo / entry.path
    3. Apply with `git apply`
    4. If git apply fails, raise with clear error identifying the patch

    Args:
        repo_dir: Path to the cloned repository where patches will be applied.
        patch_names: Ordered list of patch names to apply.
        patches_registry: List of registered PatchEntry objects.
        config_repo: Path to the configuration repository root.

    Raises:
        ValueError: If a patch name is not found in the registry.
        RuntimeError: If git apply fails for a patch.
    """
    # Build a lookup dict for quick access
    registry_map = {entry.name: entry for entry in patches_registry}

    for patch_name in patch_names:
        # Find matching PatchEntry
        if patch_name not in registry_map:
            raise ValueError(
                f"Error: [VALIDATION] Patch name not registered: '{patch_name}'. "
                f"Available patches: {', '.join(sorted(registry_map.keys()))}."
            )

        entry = registry_map[patch_name]
        patch_path = config_repo / entry.path

        # Verify patch file exists
        if not patch_path.exists():
            raise FileNotFoundError(
                f"Error: [FILE ACCESS] Patch file missing: '{patch_path}'. "
                f"The registered path for patch '{patch_name}' does not exist."
            )

        # Apply with git apply
        result = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_detail = result.stderr.strip() if result.stderr else "Unknown error"
            raise RuntimeError(
                f"Error: [GIT] Failed to apply patch '{patch_name}' "
                f"(file: {patch_path}): {error_detail}"
            )
