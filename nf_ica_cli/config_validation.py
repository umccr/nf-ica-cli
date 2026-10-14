"""Configuration validation for nf-ica CLI.

Validates cross-references, field presence, and uniqueness constraints
across all configuration files. Called by load_and_validate_config() after
parsing YAML data into dataclasses.

Error messages follow the format:
    Error: [VALIDATION] description
      Context: file/field/violation
"""

from pathlib import Path
from typing import List

from nf_ica_cli.config import (
    AppConfig,
    Context,
    IcaConfig,
    PipelineEntry,
    Workflow,
)
from nf_ica_cli.patches import PatchEntry


def validate_config(config: AppConfig) -> None:
    """Validate all configuration data for consistency and completeness.

    Checks:
    - Workflows: non-empty name/repo_uri, version fields, context cross-references
    - Contexts: non-empty names, uniqueness
    - ICA Config: tenant/project fields, context cross-references
    - Pipelines: required fields, release_status enum
    - Patches: required fields, name uniqueness, file existence

    Args:
        config: The fully parsed AppConfig instance.

    Raises:
        SystemExit: If any validation error is detected, with a message
            identifying the file, field, and violation.
    """
    # Build the set of defined context names (needed for cross-references)
    defined_contexts = [ctx.name for ctx in config.contexts]

    # Validate in order: contexts first (others depend on it)
    _validate_contexts(config.contexts)
    _validate_workflows(config.workflows, defined_contexts)
    _validate_ica_config(config.ica_config, defined_contexts)
    _validate_pipelines(config.pipelines)
    _validate_patches(config.patches, config.config_repo)


def _validation_error(file: str, field: str, violation: str) -> SystemExit:
    """Create a SystemExit with a formatted validation error message.

    Args:
        file: The configuration file where the error was found.
        field: The specific field or entry that is invalid.
        violation: Description of the violation.

    Returns:
        SystemExit instance with formatted error message.
    """
    return SystemExit(
        f"Error: [VALIDATION] {violation}\n"
        f"  Context: file={file}, field={field}"
    )


def _validate_contexts(contexts: List[Context]) -> None:
    """Validate contexts.yaml entries.

    Rules (Requirement 6.2):
    - Each context has a non-empty name
    - No two contexts share the same name
    """
    seen_names: set = set()

    for i, ctx in enumerate(contexts):
        if not ctx.name or not ctx.name.strip():
            raise _validation_error(
                "contexts.yaml",
                f"contexts[{i}].name",
                "Context name must not be empty",
            )

        if ctx.name in seen_names:
            raise _validation_error(
                "contexts.yaml",
                f"contexts[{i}].name",
                f"Duplicate context name: '{ctx.name}'. Context names must be unique",
            )
        seen_names.add(ctx.name)


def _validate_workflows(
    workflows: List[Workflow], defined_contexts: List[str]
) -> None:
    """Validate workflows.yaml entries.

    Rules (Requirement 6.1):
    - Each workflow has non-empty name and repo_uri
    - Each version has non-empty tag, git_commit_id, at least one context
    - All context values reference names in contexts.yaml
    """
    for i, wf in enumerate(workflows):
        if not wf.name or not wf.name.strip():
            raise _validation_error(
                "workflows.yaml",
                f"workflows[{i}].name",
                "Workflow name must not be empty",
            )

        if not wf.repo_uri or not wf.repo_uri.strip():
            raise _validation_error(
                "workflows.yaml",
                f"workflows[{i}].repo_uri",
                f"Workflow '{wf.name}' repo_uri must not be empty",
            )

        for j, ver in enumerate(wf.versions):
            if not ver.tag or not str(ver.tag).strip():
                raise _validation_error(
                    "workflows.yaml",
                    f"workflows[{i}].versions[{j}].tag",
                    f"Workflow '{wf.name}' version tag must not be empty",
                )

            if not ver.git_commit_id or not ver.git_commit_id.strip():
                raise _validation_error(
                    "workflows.yaml",
                    f"workflows[{i}].versions[{j}].git_commit_id",
                    f"Workflow '{wf.name}' version '{ver.tag}' git_commit_id must not be empty",
                )

            if not ver.contexts:
                raise _validation_error(
                    "workflows.yaml",
                    f"workflows[{i}].versions[{j}].contexts",
                    f"Workflow '{wf.name}' version '{ver.tag}' must have at least one context",
                )

            for ctx_val in ver.contexts:
                if ctx_val not in defined_contexts:
                    raise _validation_error(
                        "workflows.yaml",
                        f"workflows[{i}].versions[{j}].contexts",
                        f"Workflow '{wf.name}' version '{ver.tag}' references "
                        f"undefined context '{ctx_val}'. "
                        f"Available contexts: {', '.join(sorted(defined_contexts))}",
                    )


def _validate_ica_config(
    ica_config: IcaConfig, defined_contexts: List[str]
) -> None:
    """Validate ica_config.yaml entries.

    Rules (Requirement 6.3):
    - Each tenant has non-empty name and id
    - Each project has non-empty id, name, at least one context
    - All project context values reference names in contexts.yaml
    """
    for i, tenant in enumerate(ica_config.tenants):
        if not tenant.name or not tenant.name.strip():
            raise _validation_error(
                "ica_config.yaml",
                f"tenants[{i}].name",
                "Tenant name must not be empty",
            )

        if not tenant.id or not tenant.id.strip():
            raise _validation_error(
                "ica_config.yaml",
                f"tenants[{i}].id",
                f"Tenant '{tenant.name}' id must not be empty",
            )

        for j, project in enumerate(tenant.projects):
            if not project.id or not project.id.strip():
                raise _validation_error(
                    "ica_config.yaml",
                    f"tenants[{i}].projects[{j}].id",
                    f"Project in tenant '{tenant.name}' id must not be empty",
                )

            if not project.name or not project.name.strip():
                raise _validation_error(
                    "ica_config.yaml",
                    f"tenants[{i}].projects[{j}].name",
                    f"Project in tenant '{tenant.name}' name must not be empty",
                )

            if not project.contexts:
                raise _validation_error(
                    "ica_config.yaml",
                    f"tenants[{i}].projects[{j}].contexts",
                    f"Project '{project.name}' in tenant '{tenant.name}' "
                    f"must have at least one context",
                )

            for ctx_val in project.contexts:
                if ctx_val not in defined_contexts:
                    raise _validation_error(
                        "ica_config.yaml",
                        f"tenants[{i}].projects[{j}].contexts",
                        f"Project '{project.name}' in tenant '{tenant.name}' "
                        f"references undefined context '{ctx_val}'. "
                        f"Available contexts: {', '.join(sorted(defined_contexts))}",
                    )


def _validate_pipelines(pipelines: List[PipelineEntry]) -> None:
    """Validate ica_pipelines.yaml entries.

    Rules (Requirement 6.4):
    - Each entry has workflow_name, workflow_version, git_commit_id
    - release_status is one of DRAFT or RELEASED
    - At least one tenants value
    - At least one contexts value
    """
    valid_statuses = ("DRAFT", "RELEASED")

    for i, entry in enumerate(pipelines):
        if not entry.workflow_name or not entry.workflow_name.strip():
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].workflow_name",
                "Pipeline entry workflow_name must not be empty",
            )

        if not entry.workflow_version or not entry.workflow_version.strip():
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].workflow_version",
                "Pipeline entry workflow_version must not be empty",
            )

        if not entry.git_commit_id or not entry.git_commit_id.strip():
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].git_commit_id",
                "Pipeline entry git_commit_id must not be empty",
            )

        if entry.release_status not in valid_statuses:
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].release_status",
                f"Pipeline entry release_status '{entry.release_status}' is invalid. "
                f"Expected one of: {', '.join(valid_statuses)}",
            )

        if not entry.tenants:
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].tenants",
                f"Pipeline entry for '{entry.workflow_name}/{entry.workflow_version}' "
                f"must have at least one tenant",
            )

        if not entry.contexts:
            raise _validation_error(
                "ica_pipelines.yaml",
                f"pipelines[{i}].contexts",
                f"Pipeline entry for '{entry.workflow_name}/{entry.workflow_version}' "
                f"must have at least one context",
            )


def _validate_patches(patches: List[PatchEntry], config_repo: Path) -> None:
    """Validate patches.yaml entries.

    Rules (Requirement 6.5):
    - Each entry has non-empty name, path, md5sum, description
    - No two entries share the same name
    - The file at path exists in config_repo
    """
    seen_names: set = set()

    for i, entry in enumerate(patches):
        if not entry.name or not entry.name.strip():
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].name",
                "Patch entry name must not be empty",
            )

        if not entry.path or not entry.path.strip():
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].path",
                f"Patch '{entry.name}' path must not be empty",
            )

        if not entry.md5sum or not entry.md5sum.strip():
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].md5sum",
                f"Patch '{entry.name}' md5sum must not be empty",
            )

        if not entry.description or not entry.description.strip():
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].description",
                f"Patch '{entry.name}' description must not be empty",
            )

        if entry.name in seen_names:
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].name",
                f"Duplicate patch name: '{entry.name}'. Patch names must be unique",
            )
        seen_names.add(entry.name)

        # Check file existence
        patch_file = config_repo / entry.path
        if not patch_file.exists():
            raise _validation_error(
                "patches.yaml",
                f"patches[{i}].path",
                f"Patch '{entry.name}' file not found at '{entry.path}' "
                f"(resolved: {patch_file})",
            )
