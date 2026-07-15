"""Handler for the make-workflow-version subcommand.

Creates an annotated git tag encoding deployment metadata (git commit ID,
contexts, patch names, release status, and description). All validation is
performed before the tag is created (fail-fast per Requirement 3.3).
"""

from pathlib import Path
from typing import List

from nf_ica_cli.config import AppConfig
from nf_ica_cli.git_ops import create_annotated_tag, tag_exists
from nf_ica_cli.tag_codec import TagMetadata, encode_tag_message, make_tag_name
from nf_ica_cli.validators import validate_context, validate_release_status


def handle_make_workflow_version(args: dict, config: AppConfig, config_repo: Path) -> None:
    """Handle the make-workflow-version subcommand.

    Creates an annotated git tag encoding deployment metadata. All validation
    is performed before the tag is created (fail-fast).

    Flow:
    1. Extract flags from docopt args
    2. Validate release status
    3. Validate each context value against defined contexts
    4. Verify version tag is registered in workflows.yaml for the workflow
    5. Verify each patch name exists in the patches registry
    6. Generate tag name with UTC timestamp
    7. Check tag doesn't already exist
    8. Encode tag metadata as YAML
    9. Create annotated tag

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation errors or git operation failures.
    """
    # 1. Extract flags
    workflow_name: str = args["--workflow-name"]
    version_tag: str = args["--workflow-version-tag"]
    git_commit_id: str = args["--workflow-version-git-commit-id"]
    contexts: List[str] = args["--workflow-version-context"]
    patch_names: List[str] = args["--workflow-patch-name"] or []
    release_status: str = args["--release-status"]
    description: str = args["--workflow-version-description"] or ""

    # 2. Validate release status (Req 3.5)
    try:
        validate_release_status(release_status)
    except ValueError as e:
        raise SystemExit(
            f"Error: [VALIDATION] {e}"
        ) from e

    # 3. Validate each context value (Req 3.7)
    defined_context_names = [ctx.name for ctx in config.contexts]
    for ctx_value in contexts:
        try:
            validate_context(ctx_value, defined_context_names)
        except ValueError as e:
            raise SystemExit(
                f"Error: [VALIDATION] {e}"
            ) from e

    # 4. Verify version tag is registered in workflows.yaml (Req 3.6)
    workflow_found = False
    version_registered = False
    for wf in config.workflows:
        if wf.name == workflow_name:
            workflow_found = True
            for ver in wf.versions:
                if ver.tag == version_tag:
                    version_registered = True
                    break
            break

    if not workflow_found:
        raise SystemExit(
            f"Error: [VALIDATION] Workflow '{workflow_name}' not found in workflows.yaml. "
            f"The workflow must be registered before creating a version tag."
        )

    if not version_registered:
        raise SystemExit(
            f"Error: [VALIDATION] Version tag '{version_tag}' is not registered "
            f"for workflow '{workflow_name}' in workflows.yaml. "
            f"Use 'add-workflow-version' to register the version first."
        )

    # 5. Verify each patch name exists in patches registry (Req 3.4)
    registered_patch_names = {patch.name for patch in config.patches}
    for patch_name in patch_names:
        if patch_name not in registered_patch_names:
            raise SystemExit(
                f"Error: [VALIDATION] Patch name '{patch_name}' is not registered "
                f"in patches.yaml. Available patches: "
                f"{', '.join(sorted(registered_patch_names)) if registered_patch_names else '(none)'}."
            )

    # 6. Generate tag name with UTC timestamp (Req 3.1)
    tag_name = make_tag_name(workflow_name, version_tag)

    # 7. Check tag doesn't already exist (Req 3.8)
    if tag_exists(config_repo, tag_name):
        raise SystemExit(
            f"Error: [GIT] Tag '{tag_name}' already exists in the repository. "
            f"Cannot create a duplicate tag."
        )

    # 8. Encode tag metadata as YAML (Req 3.2)
    metadata = TagMetadata(
        git_commit_id=git_commit_id,
        contexts=contexts,
        patch_names=patch_names,
        release_status=release_status,
        workflow_version_description=description,
    )
    tag_message = encode_tag_message(metadata)

    # 9. Create annotated tag (Req 3.1)
    try:
        create_annotated_tag(config_repo, tag_name, tag_message)
    except RuntimeError as e:
        raise SystemExit(
            f"Error: [GIT] Failed to create annotated tag: {e}"
        ) from e
