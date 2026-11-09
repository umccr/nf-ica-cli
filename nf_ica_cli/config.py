"""Configuration loader for nf-ica CLI.

Locates the config repo, loads YAML configuration files, and parses them
into typed dataclasses for use throughout the application.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.yaml_io import load_yaml


@dataclass
class WorkflowVersion:
    """A specific tagged release of a workflow."""

    tag: str
    git_commit_id: str
    contexts: List[str]
    ica_nextflow_version: Optional[str] = None


@dataclass
class Workflow:
    """A Nextflow workflow defined by name and repository URI."""

    name: str
    repo_uri: str
    versions: List[WorkflowVersion]


@dataclass
class Context:
    """A deployment environment label."""

    name: str
    description: str


@dataclass
class OidcAuth:
    """OIDC authentication configuration for an ICA project."""

    aws_role_arn: str
    secret_arn: str


@dataclass
class IcaProject:
    """An ICA project within a tenant."""

    id: str
    name: str
    oidc_auth: List[OidcAuth]
    contexts: List[str]


@dataclass
class Tenant:
    """An ICA organisational unit containing projects."""

    name: str
    id: str
    projects: List[IcaProject]


@dataclass
class IcaConfig:
    """ICA infrastructure configuration."""

    tenants: List[Tenant]
    default_nextflow_version: str


@dataclass
class PipelineEntry:
    """A deployed pipeline instance tracked in ica_pipelines.yaml."""

    workflow_name: str
    workflow_version: str
    git_commit_id: str
    pipeline_id: str
    release_status: str  # "DRAFT" | "RELEASED"
    tenants: List[str]
    contexts: List[str]
    patch_files: List[str]
    ica_nextflow_version: str


@dataclass
class AppConfig:
    """Top-level application configuration loaded from the config repo."""

    config_repo: Path
    workflows: List[Workflow]
    contexts: List[Context]
    ica_config: IcaConfig
    pipelines: List[PipelineEntry]
    patches: List[PatchEntry]


# Expected directory structure for error messages
_EXPECTED_STRUCTURE = """\
  config/workflows.yaml
  config/contexts.yaml
  config/ica_config.yaml
  config/ica_pipelines.yaml
  config/patches.yaml
  patches/"""


def find_config_repo() -> Path:
    """Locate the config repo via NF_ICA_REPO_PATH or by traversing CWD upward.

    Resolution order:
    1. If the NF_ICA_REPO_PATH environment variable is set, use that path directly.
    2. Otherwise, search the current working directory and its parents for a
       directory containing `config/workflows.yaml`.

    Returns:
        Path to the config repo root directory.

    Raises:
        SystemExit: If NF_ICA_REPO_PATH is set but invalid, or if no config repo
            is found after reaching the filesystem root.
    """
    env_path = os.environ.get("NF_ICA_REPO_PATH")

    if env_path:
        repo_path = Path(env_path).resolve()
        if not repo_path.is_dir():
            raise SystemExit(
                f"Error: [CONFIG NOT FOUND] NF_ICA_REPO_PATH is set to '{env_path}' "
                "but the directory does not exist.\n"
                "  Please set NF_ICA_REPO_PATH to the root of the nf-ica repository.\n"
                "  Expected directory structure:\n"
                f"{_EXPECTED_STRUCTURE}"
            )
        if not (repo_path / "config" / "workflows.yaml").exists():
            raise SystemExit(
                f"Error: [CONFIG NOT FOUND] NF_ICA_REPO_PATH is set to '{env_path}' "
                "but it does not contain config/workflows.yaml.\n"
                "  Please set NF_ICA_REPO_PATH to the root of the nf-ica repository.\n"
                "  Expected directory structure:\n"
                f"{_EXPECTED_STRUCTURE}"
            )
        return repo_path

    current = Path.cwd().resolve()

    while True:
        if (current / "config" / "workflows.yaml").exists():
            return current

        parent = current.parent
        if parent == current:
            # Reached filesystem root
            raise SystemExit(
                "Error: [CONFIG NOT FOUND] No configuration repository found.\n"
                "  Searched from current directory to filesystem root.\n"
                "  Set NF_ICA_REPO_PATH to the root of the nf-ica repository,\n"
                "  or run this command from within the repository.\n"
                "  Expected directory structure:\n"
                f"{_EXPECTED_STRUCTURE}"
            )
        current = parent


def load_and_validate_config(config_repo: Path) -> AppConfig:
    """Load all YAML configuration files and parse into dataclasses.

    Loads workflows.yaml, contexts.yaml, ica_config.yaml, ica_pipelines.yaml,
    and patches.yaml (optional). Parses the raw YAML data into typed dataclasses.

    Note: Full cross-reference validation is performed in the validators module
    (task 5.3). This function handles structural parsing.

    Args:
        config_repo: Path to the configuration repository root.

    Returns:
        An AppConfig instance containing all parsed configuration.

    Raises:
        SystemExit: If a required YAML file is missing or contains invalid syntax.
    """
    config_dir = config_repo / "config"

    # Load required YAML files
    workflows_data = load_yaml(config_dir / "workflows.yaml")
    contexts_data = load_yaml(config_dir / "contexts.yaml")
    ica_config_data = load_yaml(config_dir / "ica_config.yaml")
    pipelines_data = load_yaml(config_dir / "ica_pipelines.yaml")

    # Load optional patches.yaml (empty list if missing)
    patches_path = config_dir / "patches.yaml"
    if patches_path.exists():
        patches_data = load_yaml(patches_path)
    else:
        patches_data = None

    # Parse into dataclasses
    workflows = _parse_workflows(workflows_data)
    contexts = _parse_contexts(contexts_data)
    ica_config = _parse_ica_config(ica_config_data)
    pipelines = _parse_pipelines(pipelines_data)
    patches = _parse_patches(patches_data)

    app_config = AppConfig(
        config_repo=config_repo,
        workflows=workflows,
        contexts=contexts,
        ica_config=ica_config,
        pipelines=pipelines,
        patches=patches,
    )

    # Validate cross-references and constraints
    from nf_ica_cli.config_validation import validate_config

    validate_config(app_config)

    return app_config


def _parse_workflows(data: dict) -> List[Workflow]:
    """Parse workflows.yaml data into Workflow dataclass list."""
    if data is None or "workflows" not in data:
        return []

    workflows = []
    for wf in data["workflows"]:
        versions = []
        for ver in wf.get("versions", []):
            versions.append(
                WorkflowVersion(
                    tag=str(ver["tag"]),
                    git_commit_id=str(ver["git_commit_id"]),
                    contexts=list(ver.get("contexts", [])),
                    ica_nextflow_version=(
                        str(ver["ica_nextflow_version"])
                        if ver.get("ica_nextflow_version") is not None
                        else None
                    ),
                )
            )
        workflows.append(
            Workflow(
                name=str(wf["name"]),
                repo_uri=str(wf["repo_uri"]),
                versions=versions,
            )
        )
    return workflows


def _parse_contexts(data: dict) -> List[Context]:
    """Parse contexts.yaml data into Context dataclass list."""
    if data is None or "contexts" not in data:
        return []

    contexts = []
    for ctx in data["contexts"]:
        contexts.append(
            Context(
                name=str(ctx["name"]),
                description=str(ctx.get("description", "")),
            )
        )
    return contexts


def _parse_ica_config(data: dict) -> IcaConfig:
    """Parse ica_config.yaml data into IcaConfig dataclass."""
    if data is None:
        return IcaConfig(tenants=[], default_nextflow_version="")

    tenants = []
    for tenant_data in data.get("tenants", []):
        projects = []
        for proj in tenant_data.get("projects", []):
            oidc_auths = []
            for auth in proj.get("oidc_auth", []):
                oidc_auths.append(
                    OidcAuth(
                        aws_role_arn=str(auth["aws_role_arn"]),
                        secret_arn=str(auth["secret_arn"]),
                    )
                )
            projects.append(
                IcaProject(
                    id=str(proj["id"]),
                    name=str(proj["name"]),
                    oidc_auth=oidc_auths,
                    contexts=list(proj.get("contexts", [])),
                )
            )
        tenants.append(
            Tenant(
                name=str(tenant_data["name"]),
                id=str(tenant_data["id"]),
                projects=projects,
            )
        )

    return IcaConfig(
        tenants=tenants,
        default_nextflow_version=str(data.get("default_nextflow_version", "")),
    )


def _parse_pipelines(data: dict) -> List[PipelineEntry]:
    """Parse ica_pipelines.yaml data into PipelineEntry dataclass list."""
    if data is None or "pipelines" not in data:
        return []

    pipelines_list = data["pipelines"]
    if pipelines_list is None:
        return []

    pipelines = []
    for entry in pipelines_list:
        pipelines.append(
            PipelineEntry(
                workflow_name=str(entry["workflow_name"]),
                workflow_version=str(entry["workflow_version"]),
                git_commit_id=str(entry["git_commit_id"]),
                pipeline_id=str(entry["pipeline_id"]),
                release_status=str(entry["release_status"]),
                tenants=list(entry.get("tenants", [])),
                contexts=list(entry.get("contexts", [])),
                patch_files=list(entry.get("patch_files", [])),
                ica_nextflow_version=str(entry.get("ica_nextflow_version", "")),
            )
        )
    return pipelines


def _parse_patches(data: dict) -> List[PatchEntry]:
    """Parse patches.yaml data into PatchEntry dataclass list."""
    if data is None or "patches" not in data:
        return []

    patches_list = data["patches"]
    if patches_list is None:
        return []

    patches = []
    for entry in patches_list:
        patches.append(
            PatchEntry(
                name=str(entry["name"]),
                path=str(entry["path"]),
                md5sum=str(entry["md5sum"]),
                description=str(entry.get("description", "")),
            )
        )
    return patches
