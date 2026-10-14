"""Handler for the add-workflow-version subcommand.

Registers a new workflow version in workflows.yaml, creating the workflow
entry if it doesn't already exist.
"""

from pathlib import Path
from typing import List

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from nf_ica_cli.config import AppConfig
from nf_ica_cli.validators import validate_context, validate_git_commit_id
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def handle_add_workflow_version(
    args: dict, config: AppConfig, config_repo: Path
) -> None:
    """Handle the add-workflow-version subcommand.

    Extracts flags, validates inputs, checks for URI mismatch and duplicate
    version tags, then adds the version entry to workflows.yaml.

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation failure, URI mismatch, or duplicate version.
    """
    # 1. Extract flags from docopt args
    workflow_name: str = args["--workflow-name"]
    workflow_repo_uri: str = args["--workflow-repo-uri"]
    version_tag: str = args["--workflow-version-tag"]
    git_commit_id: str = args["--workflow-version-git-commit-id"]
    version_contexts: List[str] = args["--workflow-version-context"]
    ica_nextflow_version: str = args["--workflow-ica-nextflow-version"]

    # 2. Validate git commit ID
    try:
        validate_git_commit_id(git_commit_id)
    except ValueError as e:
        raise SystemExit(
            f"Error: [VALIDATION] {e}"
        )

    # 3. Validate each context value against defined contexts
    defined_context_names = [ctx.name for ctx in config.contexts]
    for ctx_value in version_contexts:
        try:
            validate_context(ctx_value, defined_context_names)
        except ValueError as e:
            raise SystemExit(
                f"Error: [VALIDATION] {e}"
            )

    # 4. If workflow name exists, check for URI mismatch and duplicate version
    existing_workflow = None
    for wf in config.workflows:
        if wf.name == workflow_name:
            existing_workflow = wf
            break

    if existing_workflow is not None:
        # Check repo_uri matches (Req 2.3)
        if existing_workflow.repo_uri != workflow_repo_uri:
            raise SystemExit(
                f"Error: [URI MISMATCH] Workflow '{workflow_name}' already exists "
                f"with a different repository URI.\n"
                f"  Existing URI: {existing_workflow.repo_uri}\n"
                f"  Provided URI: {workflow_repo_uri}"
            )

        # Check version tag doesn't already exist (Req 2.4)
        for ver in existing_workflow.versions:
            if ver.tag == version_tag:
                raise SystemExit(
                    f"Error: [DUPLICATE VERSION] Version '{version_tag}' already "
                    f"exists for workflow '{workflow_name}'."
                )

    # 5. Load workflows.yaml raw data via load_yaml (preserves comments)
    workflows_path = config_repo / "config" / "workflows.yaml"
    raw_data = load_yaml(workflows_path)

    # 6. Build the new version entry
    version_entry = CommentedMap()
    version_entry["tag"] = version_tag
    version_entry["git_commit_id"] = git_commit_id
    contexts_seq = CommentedSeq(version_contexts)
    version_entry["contexts"] = contexts_seq
    if ica_nextflow_version:
        version_entry["ica_nextflow_version"] = ica_nextflow_version

    # 7. Modify the raw YAML data
    if raw_data is None:
        raw_data = CommentedMap()

    if "workflows" not in raw_data or raw_data["workflows"] is None:
        raw_data["workflows"] = CommentedSeq()

    if existing_workflow is not None:
        # Append to the existing workflow's versions list
        for wf_entry in raw_data["workflows"]:
            if wf_entry["name"] == workflow_name:
                if "versions" not in wf_entry or wf_entry["versions"] is None:
                    wf_entry["versions"] = CommentedSeq()
                wf_entry["versions"].append(version_entry)
                break
    else:
        # Create a new workflow entry
        new_workflow = CommentedMap()
        new_workflow["name"] = workflow_name
        new_workflow["repo_uri"] = workflow_repo_uri
        versions_list = CommentedSeq()
        versions_list.append(version_entry)
        new_workflow["versions"] = versions_list
        raw_data["workflows"].append(new_workflow)

    # 8. Save via save_yaml (preserves comments) (Req 2.8)
    save_yaml(workflows_path, raw_data)
