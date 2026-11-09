"""Handler for the update-workflow-version-release-status subcommand.

Updates a deployed DRAFT pipeline entry in one of two mutually exclusive modes:

* **Publish** (``--release-status RELEASED``): verify the deployed ICA pipeline
  still matches the configured source commit + patch set, release the ICA
  pipeline, flip ``release_status`` to RELEASED in ``ica_pipelines.yaml``, and
  publish the (previously draft) GitHub release.
* **Amend** (``--git-commit-id`` / ``--add-patch`` / ``--remove-patch``): change
  the source commit and/or patch set of a DRAFT release, rebuild the pipeline
  source, replace the ICA pipeline asset, update ``ica_pipelines.yaml`` (and
  ``workflows.yaml`` for a commit change), and refresh the GitHub release notes
  and zip asset. The entry stays DRAFT.

A pipeline already in RELEASED status cannot be changed.

ICA access uses the ``ICAV2_ACCESS_TOKEN`` environment variable (local auth),
consistent with the ``collect-all-patches`` command.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from nf_ica_cli.config import AppConfig, PipelineEntry, Workflow
from nf_ica_cli.diff_generator import generate_diffs
from nf_ica_cli.git_ops import clone_at_commit, get_github_blob_base_url
from nf_ica_cli.ica_client import release_pipeline, update_pipeline
from nf_ica_cli.patches import apply_patches
from nf_ica_cli.pipeline_exporter import export_pipeline_source
from nf_ica_cli.release_page import (
    DeploymentResult,
    create_pipeline_zip,
    generate_release_body,
    update_github_release,
)
from nf_ica_cli.validators import validate_git_commit_id, validate_release_status
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def handle_update_release_status(
    args: dict, config: AppConfig, config_repo: Path
) -> None:
    """Handle the update-workflow-version-release-status subcommand.

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation errors, state violations, or ICA/GitHub
            failures.
    """
    # 1. Extract flags.
    workflow_name: str = args["--workflow-name"]
    version_tag: str = args["--workflow-version-tag"]
    new_status: Optional[str] = args.get("--release-status")
    new_git_commit_id: Optional[str] = args.get("--git-commit-id")
    add_patches: List[str] = args.get("--add-patch") or []
    remove_patches: List[str] = args.get("--remove-patch") or []

    # 2. Determine the mode and enforce mutual exclusivity.
    edit_requested = bool(new_git_commit_id or add_patches or remove_patches)

    if new_status and edit_requested:
        raise SystemExit(
            "Error: [VALIDATION] --release-status is mutually exclusive with "
            "--git-commit-id / --add-patch / --remove-patch. Publish and amend "
            "are separate operations."
        )

    if not new_status and not edit_requested:
        raise SystemExit(
            "Error: [VALIDATION] Nothing to do: specify --release-status, or "
            "one or more of --git-commit-id / --add-patch / --remove-patch."
        )

    # 3. Resolve the pipeline entry.
    entry = _find_pipeline_entry(config, workflow_name, version_tag)

    # 4. A pipeline already RELEASED cannot be modified. Checked before any
    #    workflow/project resolution so the rejection does not depend on other
    #    config being present.
    if entry.release_status == "RELEASED":
        raise SystemExit(
            f"Error: [STATE VIOLATION] Pipeline '{workflow_name}/{version_tag}' "
            f"is already RELEASED and cannot be modified."
        )

    # 5. Resolve the owning workflow and ICA project (needed by both modes).
    workflow = _find_workflow(config, workflow_name)
    project_id = _resolve_project_id(config, entry)

    # 6. Dispatch to the requested mode.
    if new_status:
        _handle_release(
            config=config,
            config_repo=config_repo,
            entry=entry,
            workflow=workflow,
            project_id=project_id,
            new_status=new_status,
        )
    else:
        _handle_amend(
            config=config,
            config_repo=config_repo,
            entry=entry,
            workflow=workflow,
            project_id=project_id,
            new_git_commit_id=new_git_commit_id,
            add_patches=add_patches,
            remove_patches=remove_patches,
        )


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _find_pipeline_entry(
    config: AppConfig, workflow_name: str, version_tag: str
) -> PipelineEntry:
    """Return the single pipeline entry matching name + full version tag."""
    for entry in config.pipelines:
        if (
            entry.workflow_name == workflow_name
            and entry.workflow_version == version_tag
        ):
            return entry

    raise SystemExit(
        f"Error: [NOT FOUND] No pipeline entry found for workflow "
        f"'{workflow_name}' version '{version_tag}' in ica_pipelines.yaml."
    )


def _find_workflow(config: AppConfig, workflow_name: str) -> Workflow:
    """Return the workflow definition for the given name."""
    for workflow in config.workflows:
        if workflow.name == workflow_name:
            return workflow

    raise SystemExit(
        f"Error: [NOT FOUND] Workflow '{workflow_name}' not found in "
        f"workflows.yaml."
    )


def _short_version_tag(workflow_version: str) -> str:
    """Return the workflows.yaml short tag from a '<tag>__<timestamp>' value.

    The ica_pipelines.yaml ``workflow_version`` is the long-hand
    ``<version>__<timestamp>`` (e.g. ``0.6.5-rc__20261028055117``); the
    workflows.yaml registry key is the semantic prefix (``0.6.5-rc``).
    """
    return workflow_version.split("__", 1)[0]


def _resolve_project(config: AppConfig, entry: PipelineEntry):
    """Resolve the ICA project for a pipeline entry.

    A pipeline entry records its ``tenants`` and ``contexts`` but not the
    project. The project is the one inside the entry's tenant whose
    contexts intersect the entry's contexts.

    Raises:
        SystemExit: If the tenant or a matching project cannot be found.
    """
    entry_contexts = set(entry.contexts)
    tenant_names = set(entry.tenants)

    for tenant in config.ica_config.tenants:
        if tenant.name not in tenant_names:
            continue
        for project in tenant.projects:
            if entry_contexts.intersection(project.contexts):
                return project

    raise SystemExit(
        f"Error: [NOT FOUND] Could not resolve an ICA project for pipeline "
        f"'{entry.workflow_name}/{entry.workflow_version}' "
        f"(tenants={entry.tenants}, contexts={entry.contexts}) in "
        f"ica_config.yaml."
    )


def _resolve_project_id(config: AppConfig, entry: PipelineEntry) -> str:
    """Resolve the ICA project UUID for a pipeline entry."""
    return _resolve_project(config, entry).id


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_ica_token() -> None:
    """Fail fast if the ICA access token is not available."""
    if not os.environ.get("ICAV2_ACCESS_TOKEN"):
        raise SystemExit(
            "Error: [AUTH] ICAV2_ACCESS_TOKEN environment variable is not set "
            "or is empty. Set ICAV2_ACCESS_TOKEN to a valid ICA access token "
            "before running update-workflow-version-release-status."
        )


def _verify_patches_registered(
    config: AppConfig, config_repo: Path, patch_names: List[str], context: str
) -> None:
    """Verify every patch name is registered and its file exists on disk."""
    registered = {patch.name: patch for patch in config.patches}
    for patch_name in patch_names:
        if patch_name not in registered:
            raise SystemExit(
                f"Error: [VALIDATION] Patch '{patch_name}' {context} is not "
                f"registered in patches.yaml. All patches must be registered."
            )
        patch_path = config_repo / registered[patch_name].path
        if not patch_path.exists():
            raise SystemExit(
                f"Error: [FILE ACCESS] Patch file missing for patch "
                f"'{patch_name}': '{patch_path}'. The file must exist on disk."
            )


def _build_patched_source(
    config: AppConfig,
    config_repo: Path,
    workflow: Workflow,
    git_commit_id: str,
    patch_names: List[str],
    clone_dir: Path,
) -> None:
    """Clone the workflow repo at a commit and apply the given patches in-place."""
    try:
        clone_at_commit(workflow.repo_uri, git_commit_id, clone_dir)
    except RuntimeError as e:
        raise SystemExit(
            f"Error: [GIT] Failed to clone repository '{workflow.repo_uri}' at "
            f"commit '{git_commit_id}': {e}"
        ) from e

    if patch_names:
        try:
            apply_patches(
                repo_dir=clone_dir,
                patch_names=patch_names,
                patches_registry=config.patches,
                config_repo=config_repo,
            )
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            raise SystemExit(str(e)) from e


def _release_tag_name(entry: PipelineEntry) -> str:
    """Return the GitHub release tag for a pipeline entry.

    The release tag is ``<workflow_name>/<workflow_version>``, e.g.
    ``sash/0.6.5-rc__20261028055117``.
    """
    return f"{entry.workflow_name}/{entry.workflow_version}"


# ---------------------------------------------------------------------------
# Mode A: publish (--release-status RELEASED)
# ---------------------------------------------------------------------------


def _handle_release(
    config: AppConfig,
    config_repo: Path,
    entry: PipelineEntry,
    workflow: Workflow,
    project_id: str,
    new_status: str,
) -> None:
    """Verify, release on ICA, update config, and publish the GitHub release."""
    # Only RELEASED is a valid target; a release cannot revert to DRAFT.
    try:
        validate_release_status(new_status)
    except ValueError as e:
        raise SystemExit(f"Error: [VALIDATION] {e}") from e

    if new_status != "RELEASED":
        raise SystemExit(
            "Error: [VALIDATION] --release-status may only be set to RELEASED. "
            "A release cannot revert from RELEASED to DRAFT."
        )

    _require_ica_token()

    # Patches referenced by the entry must be registered and present on disk.
    _verify_patches_registered(
        config,
        config_repo,
        entry.patch_files,
        context=f"referenced by pipeline '{_release_tag_name(entry)}'",
    )

    # Integrity check: the deployed ICA pipeline must match the configured
    # source commit + patch set. Build the expected tree, export the live
    # pipeline, and fail on any difference.
    clone_dir = Path(tempfile.mkdtemp(prefix="nf-ica-verify-clone-"))
    export_dir = Path(tempfile.mkdtemp(prefix="nf-ica-verify-export-"))
    try:
        _build_patched_source(
            config=config,
            config_repo=config_repo,
            workflow=workflow,
            git_commit_id=entry.git_commit_id,
            patch_names=entry.patch_files,
            clone_dir=clone_dir,
        )

        try:
            export_pipeline_source(
                project_id=project_id,
                pipeline_id=entry.pipeline_id,
                output_dir=export_dir,
            )
        except RuntimeError as e:
            raise SystemExit(str(e)) from e

        diffs = generate_diffs(clone_dir, export_dir)
        if diffs:
            changed = ", ".join(sorted(d.relative_path for d in diffs))
            raise SystemExit(
                f"Error: [VERIFICATION] Deployed pipeline "
                f"'{_release_tag_name(entry)}' does not match its configured "
                f"source (commit '{entry.git_commit_id}' + patches "
                f"{entry.patch_files or '[]'}). Differing files: {changed}. "
                f"Refusing to release."
            )
    finally:
        _cleanup_dirs(clone_dir, export_dir)

    # Release the pipeline on ICA.
    try:
        release_pipeline(project_id=project_id, pipeline_id=entry.pipeline_id)
    except RuntimeError as e:
        raise SystemExit(str(e)) from e

    # Update ica_pipelines.yaml: flip release_status to RELEASED.
    _update_pipeline_entry_yaml(
        config_repo,
        entry,
        updates={"release_status": "RELEASED"},
    )

    # Regenerate and publish the GitHub release (clear the draft flag).
    body = _release_body(
        config=config,
        config_repo=config_repo,
        entry=entry,
        git_commit_id=entry.git_commit_id,
        patch_names=entry.patch_files,
        release_status="RELEASED",
    )
    try:
        update_github_release(
            tag_name=_release_tag_name(entry),
            release_body=body,
            artefact_paths=[],
            publish=True,
        )
    except RuntimeError as e:
        raise SystemExit(str(e)) from e

    print(
        f"Released pipeline '{_release_tag_name(entry)}' "
        f"(pipeline_id={entry.pipeline_id})."
    )


# ---------------------------------------------------------------------------
# Mode B: amend (--git-commit-id / --add-patch / --remove-patch)
# ---------------------------------------------------------------------------


def _handle_amend(
    config: AppConfig,
    config_repo: Path,
    entry: PipelineEntry,
    workflow: Workflow,
    project_id: str,
    new_git_commit_id: Optional[str],
    add_patches: List[str],
    remove_patches: List[str],
) -> None:
    """Amend a DRAFT release's commit/patches and refresh ICA + GitHub."""
    _require_ica_token()

    # Resolve the new commit (validate if provided).
    git_commit_id = entry.git_commit_id
    if new_git_commit_id:
        try:
            validate_git_commit_id(new_git_commit_id)
        except ValueError as e:
            raise SystemExit(f"Error: [VALIDATION] {e}") from e
        if new_git_commit_id == entry.git_commit_id:
            print(
                f"Info: git commit id already '{new_git_commit_id}'; "
                f"leaving unchanged."
            )
        else:
            git_commit_id = new_git_commit_id

    # Compute the new patch list, emitting info messages for no-ops.
    patch_names = _compute_patch_set(
        config=config,
        current=list(entry.patch_files),
        add_patches=add_patches,
        remove_patches=remove_patches,
    )

    # Every patch in the resulting set must be registered and present on disk.
    _verify_patches_registered(
        config,
        config_repo,
        patch_names,
        context=f"for pipeline '{_release_tag_name(entry)}'",
    )

    # Rebuild the pipeline source, replace the ICA asset, and refresh the
    # GitHub release zip from the same patched tree.
    clone_dir = Path(tempfile.mkdtemp(prefix="nf-ica-amend-clone-"))
    zip_dir = Path(tempfile.mkdtemp(prefix="nf-ica-amend-zip-"))
    try:
        _build_patched_source(
            config=config,
            config_repo=config_repo,
            workflow=workflow,
            git_commit_id=git_commit_id,
            patch_names=patch_names,
            clone_dir=clone_dir,
        )

        # Replace the deployed ICA pipeline asset.
        try:
            update_pipeline(
                project_id=project_id,
                pipeline_id=entry.pipeline_id,
                source_dir=clone_dir,
            )
        except RuntimeError as e:
            raise SystemExit(str(e)) from e

        # Build the replacement release zip.
        zip_path = (
            zip_dir
            / f"{entry.workflow_name}-{entry.workflow_version}-pipeline.zip"
        )
        create_pipeline_zip(clone_dir, zip_path)

        # Update ica_pipelines.yaml (patch_files + git_commit_id) and, for a
        # commit change, workflows.yaml too.
        _update_pipeline_entry_yaml(
            config_repo,
            entry,
            updates={
                "git_commit_id": git_commit_id,
                "patch_files": patch_names,
            },
        )
        if git_commit_id != entry.git_commit_id:
            _update_workflow_commit_yaml(
                config_repo,
                workflow_name=entry.workflow_name,
                short_tag=_short_version_tag(entry.workflow_version),
                git_commit_id=git_commit_id,
            )

        # Refresh the GitHub release notes and re-upload the zip asset.
        body = _release_body(
            config=config,
            config_repo=config_repo,
            entry=entry,
            git_commit_id=git_commit_id,
            patch_names=patch_names,
            release_status="DRAFT",
        )
        try:
            update_github_release(
                tag_name=_release_tag_name(entry),
                release_body=body,
                artefact_paths=[zip_path],
                publish=False,
            )
        except RuntimeError as e:
            raise SystemExit(str(e)) from e
    finally:
        _cleanup_dirs(clone_dir, zip_dir)

    print(
        f"Updated DRAFT pipeline '{_release_tag_name(entry)}' "
        f"(commit={git_commit_id}, patches={patch_names or '[]'})."
    )


def _compute_patch_set(
    config: AppConfig,
    current: List[str],
    add_patches: List[str],
    remove_patches: List[str],
) -> List[str]:
    """Apply add/remove operations to the current patch list.

    Duplicated adds and removals of absent patches are reported as info
    messages and skipped. Additions must reference a patch registered in
    patches.yaml. Removals are applied before additions so re-adding a removed
    patch is well-defined. Order of the surviving/added patches is preserved.
    """
    registered = {patch.name for patch in config.patches}
    result = list(current)

    for patch_name in remove_patches:
        if patch_name in result:
            result.remove(patch_name)
        else:
            print(
                f"Info: patch '{patch_name}' is not applied to this release; "
                f"nothing to remove."
            )

    for patch_name in add_patches:
        if patch_name not in registered:
            raise SystemExit(
                f"Error: [VALIDATION] Patch '{patch_name}' is not registered "
                f"in patches.yaml and cannot be added."
            )
        if patch_name in result:
            print(
                f"Info: patch '{patch_name}' is already applied to this "
                f"release; not adding again."
            )
        else:
            result.append(patch_name)

    return result


# ---------------------------------------------------------------------------
# Release body + YAML writers
# ---------------------------------------------------------------------------


def _release_body(
    config: AppConfig,
    config_repo: Path,
    entry: PipelineEntry,
    git_commit_id: str,
    patch_names: List[str],
    release_status: str,
) -> str:
    """Render the GitHub release notes for a pipeline entry's current state."""
    registry_map = {patch.name: patch for patch in config.patches}
    applied_patches = [
        registry_map[name] for name in patch_names if name in registry_map
    ]
    patch_base_url = (
        get_github_blob_base_url(config_repo) if applied_patches else ""
    )

    project = _resolve_project(config, entry)

    deployments = [
        DeploymentResult(
            project_name=project.name,
            project_id=project.id,
            tenant_name=entry.tenants[0] if entry.tenants else "",
            pipeline_id=entry.pipeline_id,
            contexts=entry.contexts,
        )
    ]

    return generate_release_body(
        workflow_name=entry.workflow_name,
        workflow_version=entry.workflow_version,
        git_commit_id=git_commit_id,
        workflow_version_description="",
        release_status=release_status,
        nextflow_version=entry.ica_nextflow_version,
        patches=applied_patches,
        patch_base_url=patch_base_url,
        deployments=deployments,
        skipped_projects=[],
    )


def _update_pipeline_entry_yaml(
    config_repo: Path,
    entry: PipelineEntry,
    updates: dict,
) -> None:
    """Apply field updates to the matching entry in ica_pipelines.yaml."""
    pipelines_path = config_repo / "config" / "ica_pipelines.yaml"
    data = load_yaml(pipelines_path)

    if data and data.get("pipelines"):
        for raw_entry in data["pipelines"]:
            if (
                str(raw_entry.get("workflow_name", "")) == entry.workflow_name
                and str(raw_entry.get("workflow_version", ""))
                == entry.workflow_version
            ):
                for key, value in updates.items():
                    raw_entry[key] = value
                break

    save_yaml(pipelines_path, data)


def _update_workflow_commit_yaml(
    config_repo: Path,
    workflow_name: str,
    short_tag: str,
    git_commit_id: str,
) -> None:
    """Update git_commit_id for a workflow version in workflows.yaml."""
    workflows_path = config_repo / "config" / "workflows.yaml"
    data = load_yaml(workflows_path)

    if data and data.get("workflows"):
        for wf in data["workflows"]:
            if str(wf.get("name", "")) != workflow_name:
                continue
            for ver in wf.get("versions", []) or []:
                if str(ver.get("tag", "")) == short_tag:
                    ver["git_commit_id"] = git_commit_id
                    break
            break

    save_yaml(workflows_path, data)


def _cleanup_dirs(*dirs: Path) -> None:
    """Remove temporary directories, warning to stderr on failure."""
    for temp_dir in dirs:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if temp_dir.exists():
                print(
                    f"Warning: [CLEANUP] Failed to remove temporary directory "
                    f"'{temp_dir}'.",
                    file=sys.stderr,
                )
        except OSError as e:
            print(
                f"Warning: [CLEANUP] Failed to remove temporary directory "
                f"'{temp_dir}': {e}.",
                file=sys.stderr,
            )
