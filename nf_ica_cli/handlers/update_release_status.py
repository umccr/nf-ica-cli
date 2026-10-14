"""Handler for the update-workflow-version-release-status subcommand.

Transitions a pipeline entry's release_status in ICA_Pipelines_Yaml,
enforcing state transition rules and verifying patch integrity when releasing.
"""

import sys
from pathlib import Path

from nf_ica_cli.config import AppConfig
from nf_ica_cli.validators import validate_release_status
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def handle_update_release_status(
    args: dict, config: AppConfig, config_repo: Path
) -> None:
    """Handle the update-workflow-version-release-status subcommand.

    Flow:
    1. Extract --workflow-name, --workflow-version-tag, --release-status
    2. Validate release status value (Req 4.3)
    3. Find matching pipeline entry in config.pipelines (Req 4.1)
    4. If not found: raise SystemExit (Req 4.2)
    5. If current status is RELEASED and new status is DRAFT: reject (Req 4.4)
    6. If current status == new status: exit 0 no-op (Req 4.5)
    7. When releasing (DRAFT→RELEASED): verify patches exist (Req 4.6)
    8. Load raw YAML, update field, save preserving comments (Req 4.7)

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation errors or state violations.
    """
    # 1. Extract flags
    workflow_name: str = args["--workflow-name"]
    version_tag: str = args["--workflow-version-tag"]
    new_status: str = args["--release-status"]

    # 2. Validate release status value (Req 4.3)
    try:
        validate_release_status(new_status)
    except ValueError as e:
        raise SystemExit(
            f"Error: [VALIDATION] {e}"
        ) from e

    # 3. Find matching pipeline entry (Req 4.1)
    matching_entry = None
    for entry in config.pipelines:
        if entry.workflow_name == workflow_name and entry.workflow_version == version_tag:
            matching_entry = entry
            break

    # 4. If not found: raise SystemExit (Req 4.2)
    if matching_entry is None:
        raise SystemExit(
            f"Error: [NOT FOUND] No pipeline entry found for workflow "
            f"'{workflow_name}' version '{version_tag}' in ica_pipelines.yaml."
        )

    current_status = matching_entry.release_status

    # 5. Reject RELEASED → DRAFT transition (Req 4.4)
    if current_status == "RELEASED" and new_status == "DRAFT":
        raise SystemExit(
            f"Error: [STATE VIOLATION] Cannot revert release status from "
            f"RELEASED to DRAFT for workflow '{workflow_name}' version "
            f"'{version_tag}'. Status transitions from RELEASED to DRAFT "
            f"are not permitted."
        )

    # 6. Idempotent no-op: same status (Req 4.5)
    if current_status == new_status:
        sys.exit(0)

    # 7. When releasing (DRAFT → RELEASED): verify patches (Req 4.6)
    if new_status == "RELEASED" and matching_entry.patch_files:
        # Build lookup of registered patches
        registered_patches = {patch.name: patch for patch in config.patches}

        for patch_name in matching_entry.patch_files:
            # Check patch is registered in patches.yaml
            if patch_name not in registered_patches:
                raise SystemExit(
                    f"Error: [VALIDATION] Patch '{patch_name}' referenced by "
                    f"pipeline '{workflow_name}/{version_tag}' is not registered "
                    f"in patches.yaml. All patches must be registered before "
                    f"releasing."
                )

            # Check patch file exists on disk
            patch_entry = registered_patches[patch_name]
            patch_file_path = config_repo / patch_entry.path
            if not patch_file_path.exists():
                raise SystemExit(
                    f"Error: [FILE ACCESS] Patch file missing for patch "
                    f"'{patch_name}': '{patch_file_path}'. The file must exist "
                    f"on disk before releasing."
                )

    # 8. Load raw YAML, update field, save preserving comments (Req 4.7)
    pipelines_path = config_repo / "config" / "ica_pipelines.yaml"
    pipelines_data = load_yaml(pipelines_path)

    # Find matching entry in raw YAML data and update release_status
    if pipelines_data and "pipelines" in pipelines_data and pipelines_data["pipelines"]:
        for raw_entry in pipelines_data["pipelines"]:
            if (
                str(raw_entry.get("workflow_name", "")) == workflow_name
                and str(raw_entry.get("workflow_version", "")) == version_tag
            ):
                raw_entry["release_status"] = new_status
                break

    save_yaml(pipelines_path, pipelines_data)
