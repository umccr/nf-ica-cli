"""Handler for the gh-actions-deploy-workflow subcommand.

Deploys a workflow version to ICA projects matching the deployment contexts.
Orchestrates: tag retrieval, context filtering, OIDC auth, repo cloning,
patch application, pipeline create/update, pipeline registry update, and
GitHub Release creation.
"""

import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

from nf_ica_cli.config import AppConfig, IcaProject, Tenant
from nf_ica_cli.git_ops import clone_at_commit, get_tag_message
from nf_ica_cli.ica_client import (
    authenticate_oidc,
    create_pipeline,
    find_existing_pipeline,
    update_existing_pipeline,
)
from nf_ica_cli.patches import apply_patches
from nf_ica_cli.release_page import (
    DeploymentResult,
    create_github_release,
    create_pipeline_zip,
    generate_release_body,
)
from nf_ica_cli.tag_codec import decode_tag_message
from nf_ica_cli.yaml_io import load_yaml, save_yaml


logger = logging.getLogger(__name__)


def filter_projects_by_context(
    tenants: List[Tenant], deployment_contexts: List[str]
) -> List[Tuple[Tenant, IcaProject]]:
    """Filter ICA projects by deployment context intersection.

    Returns all (tenant, project) tuples where the project's context list
    shares at least one element with the deployment context list.

    Args:
        tenants: List of ICA tenants, each containing projects with contexts.
        deployment_contexts: List of deployment context strings to match against.

    Returns:
        List of (Tenant, IcaProject) tuples for projects whose contexts
        share at least one value with the deployment contexts.
    """
    target_contexts = set(deployment_contexts)
    targets: List[Tuple[Tenant, IcaProject]] = []

    for tenant in tenants:
        for project in tenant.projects:
            project_contexts = set(project.contexts)
            if project_contexts & target_contexts:
                targets.append((tenant, project))

    return targets


def handle_deploy_workflow(
    args: dict, config: AppConfig, config_repo: Path
) -> None:
    """Handle the gh-actions-deploy-workflow subcommand.

    Flow:
    1. Extract --workflow-name, --workflow-version, --annotated-tag-name
    2. Get tag message via git_ops.get_tag_message (Req 5.1)
    3. Decode tag message via tag_codec.decode_tag_message → TagMetadata
    4. Find the workflow in config.workflows to get repo_uri
    5. Identify target projects: filter ICA projects where project.contexts
       intersects tag metadata.contexts (Req 5.2)
    6. If no projects match: raise SystemExit (Req 5.3)
    7. Clone repo at commit into temp directory (Req 5.6)
    8. Apply patches to clone in order (Req 5.7, 5.8)
    9. For each target project:
       a. Authenticate OIDC (Req 5.4)
       b. If auth fails: log, record skip, continue (Req 5.5)
       c. Find existing pipeline via find_existing_pipeline (Req 5.9)
       d. If exists: update_existing_pipeline; if not: create_pipeline
       e. Record DeploymentResult
    10. Record pipeline IDs in ica_pipelines.yaml (Req 5.10, 5.11)
    11. If at least one deployment succeeded:
        a. Create zip of patched source (Req 5.13)
        b. Generate release body via release_page.generate_release_body (Req 5.14)
        c. Create GitHub release via release_page.create_github_release
    12. If all deployments failed (zero successes): skip release (Req 5.15)
    13. If partial failure: exit non-zero with summary (Req 5.12)
    14. Clean up temp directory

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On validation errors or deployment failures.
    """
    # 1. Extract flags
    workflow_name: str = args["--workflow-name"]
    workflow_version: str = args["--workflow-version"]
    annotated_tag_name: str = args["--annotated-tag-name"]

    # 2. Get tag message (Req 5.1)
    try:
        tag_message = get_tag_message(config_repo, annotated_tag_name)
    except RuntimeError as e:
        raise SystemExit(
            f"Error: [GIT] Failed to retrieve annotated tag message for "
            f"'{annotated_tag_name}': {e}"
        ) from e

    # 3. Decode tag message (Req 5.1)
    try:
        tag_metadata = decode_tag_message(tag_message)
    except ValueError as e:
        raise SystemExit(
            f"Error: [TAG DECODE] {e}"
        ) from e

    # 4. Find the workflow in config to get repo_uri
    workflow = None
    for wf in config.workflows:
        if wf.name == workflow_name:
            workflow = wf
            break

    if workflow is None:
        raise SystemExit(
            f"Error: [NOT FOUND] Workflow '{workflow_name}' not found in "
            f"workflows.yaml."
        )

    repo_uri = workflow.repo_uri

    # Determine the Nextflow version to use
    nextflow_version = config.ica_config.default_nextflow_version

    # Check if the specific workflow version overrides the default NF version
    for ver in workflow.versions:
        if ver.tag == workflow_version:
            if ver.ica_nextflow_version:
                nextflow_version = ver.ica_nextflow_version
            break

    # 5. Identify target projects (Req 5.2)
    targets = filter_projects_by_context(
        config.ica_config.tenants, tag_metadata.contexts
    )

    # 6. If no projects match: raise SystemExit (Req 5.3)
    if not targets:
        raise SystemExit(
            f"Error: [NO TARGETS] No ICA projects match the deployment "
            f"contexts {sorted(tag_metadata.contexts)}. Check that projects in "
            f"ica_config.yaml have matching context values."
        )

    # 7. Clone repo at commit into temp directory (Req 5.6)
    clone_dir = Path(tempfile.mkdtemp(prefix="nf-ica-deploy-"))
    try:
        _deploy_to_targets(
            clone_dir=clone_dir,
            repo_uri=repo_uri,
            tag_metadata=tag_metadata,
            config=config,
            config_repo=config_repo,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            nextflow_version=nextflow_version,
            annotated_tag_name=annotated_tag_name,
            targets=targets,
        )
    finally:
        # 14. Clean up temp directory
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)


def _deploy_to_targets(
    clone_dir: Path,
    repo_uri: str,
    tag_metadata,
    config: AppConfig,
    config_repo: Path,
    workflow_name: str,
    workflow_version: str,
    nextflow_version: str,
    annotated_tag_name: str,
    targets: List[Tuple[Tenant, "IcaProject"]],
) -> None:
    """Execute the deployment flow after temp directory setup.

    Separated to allow clean try/finally for temp dir cleanup in caller.
    """
    from nf_ica_cli.tag_codec import TagMetadata

    # Clone the repository
    try:
        clone_at_commit(repo_uri, tag_metadata.git_commit_id, clone_dir)
    except RuntimeError as e:
        raise SystemExit(
            f"Error: [GIT] Failed to clone repository '{repo_uri}' at commit "
            f"'{tag_metadata.git_commit_id}': {e}"
        ) from e

    # 8. Apply patches in order (Req 5.7, 5.8)
    if tag_metadata.patch_names:
        try:
            apply_patches(
                repo_dir=clone_dir,
                patch_names=tag_metadata.patch_names,
                patches_registry=config.patches,
                config_repo=config_repo,
            )
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            raise SystemExit(str(e)) from e

    # 9. Deploy to each target project
    successful_deployments: List[DeploymentResult] = []
    skipped_projects: List[str] = []

    for tenant, project in targets:
        # Use the first OIDC auth entry for the project
        if not project.oidc_auth:
            logger.warning(
                f"No OIDC auth configured for project '{project.name}', skipping."
            )
            skipped_projects.append(project.name)
            continue

        oidc_auth = project.oidc_auth[0]

        # 9a. Authenticate OIDC (Req 5.4)
        try:
            authenticate_oidc(
                aws_role_arn=oidc_auth.aws_role_arn,
                secret_arn=oidc_auth.secret_arn,
            )
        except RuntimeError as e:
            # 9b. Auth failure: log, record skip, continue (Req 5.5)
            logger.warning(
                f"OIDC authentication failed for project '{project.name}' "
                f"(tenant: {tenant.name}): {e}"
            )
            skipped_projects.append(project.name)
            continue

        # 9c. Find existing pipeline (Req 5.9)
        try:
            existing_pipeline_id = find_existing_pipeline(
                project_id=project.id,
                workflow_name=workflow_name,
                version=workflow_version,
            )
        except RuntimeError as e:
            logger.warning(
                f"Failed to check existing pipeline in project '{project.name}': {e}"
            )
            skipped_projects.append(project.name)
            continue

        # 9d. Create or update pipeline
        try:
            description = (
                tag_metadata.workflow_version_description
                or f"{workflow_name} v{workflow_version}"
            )

            if existing_pipeline_id:
                update_existing_pipeline(
                    project_id=project.id,
                    pipeline_id=existing_pipeline_id,
                    source_dir=clone_dir,
                    nextflow_version=nextflow_version,
                    description=description,
                )
                pipeline_id = existing_pipeline_id
            else:
                pipeline_id = create_pipeline(
                    project_id=project.id,
                    workflow_name=workflow_name,
                    version=workflow_version,
                    source_dir=clone_dir,
                    nextflow_version=nextflow_version,
                    description=description,
                )
        except RuntimeError as e:
            logger.warning(
                f"Pipeline deployment failed for project '{project.name}' "
                f"(tenant: {tenant.name}): {e}"
            )
            skipped_projects.append(project.name)
            continue

        # 9e. Record DeploymentResult
        successful_deployments.append(
            DeploymentResult(
                project_name=project.name,
                project_id=project.id,
                tenant_name=tenant.name,
                pipeline_id=pipeline_id,
                contexts=project.contexts,
            )
        )

    # 10. Record pipeline IDs in ica_pipelines.yaml (Req 5.10, 5.11)
    if successful_deployments:
        _record_pipelines(
            config_repo=config_repo,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            tag_metadata=tag_metadata,
            nextflow_version=nextflow_version,
            deployments=successful_deployments,
        )

    # 11. Create GitHub Release if at least one deployment succeeded
    if successful_deployments:
        # 11a. Create zip of patched source (Req 5.13)
        zip_output_path = clone_dir.parent / f"{workflow_name}-{workflow_version}-pipeline.zip"
        create_pipeline_zip(clone_dir, zip_output_path)

        # 11b. Generate release body (Req 5.14)
        release_body = generate_release_body(
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            git_commit_id=tag_metadata.git_commit_id,
            workflow_version_description=tag_metadata.workflow_version_description,
            release_status=tag_metadata.release_status,
            nextflow_version=nextflow_version,
            patch_names=tag_metadata.patch_names,
            deployments=successful_deployments,
            skipped_projects=skipped_projects,
        )

        # 11c. Create GitHub Release (Req 5.14)
        try:
            create_github_release(
                tag_name=annotated_tag_name,
                release_body=release_body,
                artefact_paths=[zip_output_path],
            )
        except RuntimeError as e:
            logger.error(f"Failed to create GitHub Release: {e}")
            # Don't fail the entire run for release creation failure
            # The pipelines were already deployed successfully

    # 12. If all deployments failed: skip release (Req 5.15) - handled above

    # 13. Partial failure: exit non-zero with summary (Req 5.12)
    if skipped_projects and successful_deployments:
        summary = (
            f"Partial deployment completed.\n"
            f"  Succeeded: {', '.join(d.project_name for d in successful_deployments)}\n"
            f"  Skipped (auth/deployment failure): {', '.join(skipped_projects)}"
        )
        print(summary, file=sys.stderr)
        sys.exit(1)

    # If all deployments failed (no successes) and we had skips
    if skipped_projects and not successful_deployments:
        raise SystemExit(
            f"Error: [DEPLOYMENT] All deployments failed. "
            f"Skipped projects: {', '.join(skipped_projects)}"
        )


def _record_pipelines(
    config_repo: Path,
    workflow_name: str,
    workflow_version: str,
    tag_metadata,
    nextflow_version: str,
    deployments: List[DeploymentResult],
) -> None:
    """Record deployed pipeline IDs in ica_pipelines.yaml.

    Loads the raw YAML to preserve comments, adds or updates entries,
    then saves back.
    """
    pipelines_path = config_repo / "config" / "ica_pipelines.yaml"
    pipelines_data = load_yaml(pipelines_path)

    if pipelines_data is None:
        pipelines_data = {}

    if "pipelines" not in pipelines_data or pipelines_data["pipelines"] is None:
        pipelines_data["pipelines"] = []

    for deployment in deployments:
        # Check if an entry already exists for this workflow/version/project
        existing_idx = None
        for idx, entry in enumerate(pipelines_data["pipelines"]):
            if (
                str(entry.get("workflow_name", "")) == workflow_name
                and str(entry.get("workflow_version", "")) == workflow_version
                and str(entry.get("pipeline_id", "")) == deployment.pipeline_id
            ):
                existing_idx = idx
                break

        new_entry = {
            "workflow_name": workflow_name,
            "workflow_version": workflow_version,
            "git_commit_id": tag_metadata.git_commit_id,
            "pipeline_id": deployment.pipeline_id,
            "release_status": tag_metadata.release_status,
            "tenants": [deployment.tenant_name],
            "contexts": deployment.contexts,
            "patch_files": tag_metadata.patch_names,
            "ica_nextflow_version": nextflow_version,
        }

        if existing_idx is not None:
            pipelines_data["pipelines"][existing_idx] = new_entry
        else:
            pipelines_data["pipelines"].append(new_entry)

    save_yaml(pipelines_path, pipelines_data)
