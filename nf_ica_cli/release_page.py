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

from nf_ica_cli.patches import PatchEntry


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
    patches: List[PatchEntry],
    patch_base_url: str,
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
    - Table of applied patches (name, URL permalink, md5sum, description), if any
    - List of skipped projects due to auth failures (if any)

    Args:
        patches: Ordered list of applied PatchEntry objects for this release.
        patch_base_url: GitHub blob base URL pinned at a commit
            (e.g. ``https://github.com/owner/repo/blob/<sha>``) used to build
            each patch's permalink by joining it with the patch's repo-relative
            path.
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
    if patches:
        doc.add_heading("Applied Patches", level=2)
        base = patch_base_url.rstrip("/")
        patch_header = ["Name", "URL", "MD5sum", "Description"]
        patch_rows = [
            [
                p.name,
                f"[{p.path}]({base}/{p.path.lstrip('/')})",
                f"`{p.md5sum}`",
                p.description,
            ]
            for p in patches
        ]
        doc.add_table(patch_header, patch_rows)

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
    draft: bool = False,
) -> None:
    """Create a GitHub Release using the `gh` CLI.

    Attaches the pipeline zip and any other artefacts. The release title is set
    explicitly to the tag name so GitHub does not derive it from the annotated
    tag message.
    Uses `gh release create <tag> --title <tag> --notes <body> [--draft] <artefact_paths>...`

    Args:
        tag_name: The git tag name to create the release for.
        release_body: The markdown body for the release notes.
        artefact_paths: List of file paths to attach as release artefacts.
        draft: If True, create the release as a GitHub draft (not published).

    Raises:
        RuntimeError: If the `gh` CLI command fails.
    """
    cmd = [
        "gh",
        "release",
        "create",
        tag_name,
        "--title",
        tag_name,
        "--notes",
        release_body,
    ]

    if draft:
        cmd.append("--draft")

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


def update_github_release(
    tag_name: str,
    release_body: str,
    artefact_paths: List[Path],
    publish: bool = False,
) -> None:
    """Update an existing GitHub Release's notes and artefacts via the `gh` CLI.

    Edits the release notes (``gh release edit``) and, when artefacts are
    supplied, re-uploads them with ``--clobber`` so existing assets of the same
    name are replaced (``gh release upload``). When ``publish`` is True the
    release is also moved out of draft state (``gh release edit --draft=false``).

    Args:
        tag_name: The git tag name identifying the release to update.
        release_body: The new markdown body for the release notes.
        artefact_paths: Artefacts to (re-)upload, replacing same-named assets.
            Pass an empty list to leave assets untouched.
        publish: If True, publish the release (clear its draft flag).

    Raises:
        RuntimeError: If any `gh` CLI command fails.
    """
    edit_cmd = [
        "gh",
        "release",
        "edit",
        tag_name,
        "--title",
        tag_name,
        "--notes",
        release_body,
    ]
    if publish:
        edit_cmd.append("--draft=false")

    _run_gh(edit_cmd, tag_name, action="update")

    if artefact_paths:
        upload_cmd = ["gh", "release", "upload", tag_name]
        for path in artefact_paths:
            upload_cmd.append(str(path))
        upload_cmd.append("--clobber")
        _run_gh(upload_cmd, tag_name, action="upload artefacts for")


def _run_gh(cmd: List[str], tag_name: str, action: str) -> None:
    """Run a `gh` CLI command, raising RuntimeError with context on failure.

    Args:
        cmd: The full command to run (starting with ``gh``).
        tag_name: The release tag, used only for error messages.
        action: Human-readable action phrase for error messages, e.g.
            ``"update"`` or ``"upload artefacts for"``.

    Raises:
        RuntimeError: If the command exits non-zero or `gh` is not installed.
    """
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Error: [GitHub Release] Failed to {action} release for tag "
            f"'{tag_name}'\n"
            f"  Context: {e.stderr.strip()}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "Error: [GitHub Release] The 'gh' CLI tool is not installed or not in PATH\n"
            "  Context: Install GitHub CLI from https://cli.github.com/"
        ) from e
