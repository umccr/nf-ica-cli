"""Release page generator for GitHub Releases.

Uses snakemd to programmatically generate the GitHub Release page markdown body,
and the GitHub CLI (`gh`) to create the release with artefacts.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List
import subprocess
import zipfile

import snakemd


@dataclass
class DeploymentResult:
    """Result of a successful pipeline deployment to an ICA project."""

    project_name: str
    project_id: str
    tenant_name: str
    pipeline_id: str
    contexts: List[str]


def generate_release_body(
    workflow_name: str,
    workflow_version: str,
    git_commit_id: str,
    workflow_version_description: str,
    release_status: str,
    nextflow_version: str,
    patch_names: List[str],
    deployments: List[DeploymentResult],
    skipped_projects: List[str],
) -> str:
    """Generate GitHub Release body as markdown using snakemd.

    The document includes:
    - Workflow name and version header
    - Git commit ID
    - Workflow version description (if provided)
    - Release status
    - Nextflow version
    - Table of deployed pipelines (project name, tenant, pipeline ID, contexts)
    - List of applied patches (if any)
    - List of skipped projects due to auth failures (if any)
    """
    doc = snakemd.new_doc()
    doc.add_heading(f"{workflow_name} v{workflow_version}", level=1)
    doc.add_paragraph(f"**Commit:** `{git_commit_id}`")

    if workflow_version_description:
        doc.add_paragraph(f"**Description:** {workflow_version_description}")

    doc.add_paragraph(f"**Release Status:** {release_status}")
    doc.add_paragraph(f"**Nextflow Version:** {nextflow_version}")

    # Deployment table
    doc.add_heading("Deployments", level=2)
    header = ["Project", "Tenant", "Pipeline ID", "Contexts"]
    rows = [
        [
            d.project_name,
            d.tenant_name,
            f"`{d.pipeline_id}`",
            ", ".join(d.contexts),
        ]
        for d in deployments
    ]
    doc.add_table(header, rows)

    # Patches
    if patch_names:
        doc.add_heading("Applied Patches", level=2)
        doc.add_unordered_list(patch_names)

    # Skipped projects
    if skipped_projects:
        doc.add_heading("Skipped Projects (Auth Failure)", level=2)
        doc.add_unordered_list(skipped_projects)

    return str(doc)


def create_pipeline_zip(source_dir: Path, output_path: Path) -> Path:
    """Create a zip archive of the patched pipeline source directory.

    Args:
        source_dir: Path to the patched pipeline source directory.
        output_path: Path where the zip file should be created.

    Returns:
        The path to the created zip file.
    """
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir)
                zf.write(file_path, arcname)

    return output_path


def create_github_release(
    tag_name: str,
    release_body: str,
    artefact_paths: List[Path],
) -> None:
    """Create a GitHub Release using the `gh` CLI.

    Attaches the pipeline zip and any other artefacts.
    Uses `gh release create <tag> --notes <body> <artefact_paths>...`

    Args:
        tag_name: The git tag name to create the release for.
        release_body: The markdown body for the release notes.
        artefact_paths: List of file paths to attach as release artefacts.

    Raises:
        RuntimeError: If the `gh` CLI command fails.
    """
    cmd = [
        "gh",
        "release",
        "create",
        tag_name,
        "--notes",
        release_body,
    ]

    for path in artefact_paths:
        cmd.append(str(path))

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Error: [GitHub Release] Failed to create release for tag '{tag_name}'\n"
            f"  Context: {e.stderr.strip()}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "Error: [GitHub Release] The 'gh' CLI tool is not installed or not in PATH\n"
            "  Context: Install GitHub CLI from https://cli.github.com/"
        ) from e
