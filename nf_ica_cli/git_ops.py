"""Git operations for nf-ica-cli.

Provides functions for creating annotated tags, checking tag existence,
cloning repositories at specific commits, and retrieving tag messages.
All operations use subprocess to invoke the git CLI.
"""

import subprocess
from pathlib import Path


def _run_git(
    args: list[str],
    cwd: Path,
    error_context: str,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and raise RuntimeError on failure.

    Parameters
    ----------
    args : list[str]
        The git command arguments (without the leading 'git').
    cwd : Path
        Working directory for the command.
    error_context : str
        Human-readable context for error messages.

    Returns
    -------
    subprocess.CompletedProcess[str]
        The completed process result.

    Raises
    ------
    RuntimeError
        If the git command exits with a non-zero return code.
    """
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{error_context}: command {cmd!r} exited with code "
            f"{result.returncode}: {result.stderr.strip()}"
        )
    return result


def create_annotated_tag(
    repo_dir: Path,
    tag_name: str,
    message: str,
) -> None:
    """Create an annotated git tag in the given repository.

    Parameters
    ----------
    repo_dir : Path
        Path to the git repository.
    tag_name : str
        Name for the new tag.
    message : str
        Annotation message for the tag.

    Raises
    ------
    RuntimeError
        If the git tag command fails (e.g., tag already exists).
    """
    _run_git(
        ["tag", "-a", tag_name, "-m", message],
        cwd=repo_dir,
        error_context=f"Failed to create annotated tag '{tag_name}'",
    )


def tag_exists(repo_dir: Path, tag_name: str) -> bool:
    """Check if a tag already exists in the repository.

    Parameters
    ----------
    repo_dir : Path
        Path to the git repository.
    tag_name : str
        Tag name to check.

    Returns
    -------
    bool
        True if the tag exists, False otherwise.
    """
    result = _run_git(
        ["tag", "-l", tag_name],
        cwd=repo_dir,
        error_context=f"Failed to list tags matching '{tag_name}'",
    )
    return result.stdout.strip() != ""


def clone_at_commit(
    repo_uri: str,
    commit_id: str,
    target_dir: Path,
) -> None:
    """Clone a repository and checkout a specific commit.

    Performs a full clone followed by a checkout of the specified commit.

    Parameters
    ----------
    repo_uri : str
        URI of the git repository to clone.
    commit_id : str
        Git commit hash to checkout after cloning.
    target_dir : Path
        Directory to clone into.

    Raises
    ------
    RuntimeError
        If the clone or checkout command fails.
    """
    # Clone the repository
    cmd = ["git", "clone", repo_uri, str(target_dir)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to clone repository '{repo_uri}': command "
            f"{cmd!r} exited with code {result.returncode}: "
            f"{result.stderr.strip()}"
        )

    # Checkout the specific commit
    _run_git(
        ["checkout", commit_id],
        cwd=target_dir,
        error_context=f"Failed to checkout commit '{commit_id}' in '{target_dir}'",
    )


def ensure_on_up_to_date_main(repo_dir: Path) -> None:
    """Ensure the repository is on the main branch and up-to-date with its remote.

    Fetches the remote tracking branch and compares the local HEAD against
    the remote main. Fails if:
    - The current branch is not 'main'
    - The local main is behind the remote (needs pull)
    - There is no remote tracking branch configured

    Parameters
    ----------
    repo_dir : Path
        Path to the git repository.

    Raises
    ------
    RuntimeError
        If the branch is not main or if the local branch is behind the remote.
    """
    # 1. Check we're on the main branch
    result = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_dir,
        error_context="Failed to determine current branch",
    )
    current_branch = result.stdout.strip()
    if current_branch != "main":
        raise RuntimeError(
            f"Current branch is '{current_branch}', but 'deploy-workflow-version' "
            f"can only be run on the 'main' branch."
        )

    # 2. Fetch the latest from the remote tracking branch
    _run_git(
        ["fetch", "origin", "main"],
        cwd=repo_dir,
        error_context="Failed to fetch 'origin/main'",
    )

    # 3. Check local main is not behind origin/main
    result = _run_git(
        ["rev-list", "--count", "HEAD..origin/main"],
        cwd=repo_dir,
        error_context="Failed to compare local branch with 'origin/main'",
    )
    behind_count = int(result.stdout.strip())
    if behind_count > 0:
        raise RuntimeError(
            f"Local 'main' is {behind_count} commit(s) behind 'origin/main'. "
            f"Please pull the latest changes before creating a workflow version tag."
        )


def get_tag_message(repo_dir: Path, tag_name: str) -> str:
    """Retrieve the message of an annotated tag.

    Parameters
    ----------
    repo_dir : Path
        Path to the git repository.
    tag_name : str
        Name of the tag to retrieve the message from.

    Returns
    -------
    str
        The tag message with trailing whitespace stripped.

    Raises
    ------
    RuntimeError
        If the git command fails.
    """
    result = _run_git(
        ["tag", "-l", "--format=%(contents)", tag_name],
        cwd=repo_dir,
        error_context=f"Failed to retrieve message for tag '{tag_name}'",
    )
    return result.stdout.strip()
