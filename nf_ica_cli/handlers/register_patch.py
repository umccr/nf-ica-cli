"""Handler for the register-patch subcommand.

Registers a patch file by content hash, stores it in the patches/ directory,
and updates patches.yaml with the new entry.
"""

from pathlib import Path

from nf_ica_cli.config import AppConfig
from nf_ica_cli.patches import register_patch
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def handle_register_patch(args: dict, config: AppConfig, config_repo: Path) -> None:
    """Handle the register-patch subcommand.

    Extracts --file, --name, --description from args, registers the patch
    via the patches module, and updates patches.yaml.

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation errors or file access issues.
    """
    source_file = Path(args["--file"])
    name = args["--name"]
    description = args["--description"]

    try:
        # register_patch handles: name validation, collision check, MD5, file copy
        patch_entry = register_patch(
            config_repo=config_repo,
            source_file=source_file,
            name=name,
            description=description,
            existing_patches=config.patches,
        )
    except (ValueError, FileNotFoundError, PermissionError) as e:
        raise SystemExit(str(e)) from e

    # Update patches.yaml
    patches_path = config_repo / "config" / "patches.yaml"

    if patches_path.exists():
        patches_data = load_yaml(patches_path)
    else:
        patches_data = {}

    # Ensure 'patches' key exists as a list
    if patches_data is None:
        patches_data = {}
    if "patches" not in patches_data or patches_data["patches"] is None:
        patches_data["patches"] = []

    # Append the new entry
    patches_data["patches"].append(
        {
            "name": patch_entry.name,
            "path": patch_entry.path,
            "md5sum": patch_entry.md5sum,
            "description": patch_entry.description,
        }
    )

    save_yaml(patches_path, patches_data)
