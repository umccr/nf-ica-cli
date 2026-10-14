"""Handler for the collect-all-patches subcommand.

Reverse-engineers the set of patches applied to a Nextflow pipeline deployed on
ICA. Given a source repository at a specific commit and a pipeline on ICA, the
handler:

1. Clones the source repository at the specified commit.
2. Exports the ICA pipeline source files.
3. Generates unified diffs between the two directory trees.
4. Interactively registers the resulting patches into the content-addressed
   patch store (via :func:`nf_ica_cli.patch_registrar.register_collected_patches`).

Both temporary directories (clone and export) are created with
``tempfile.mkdtemp`` and removed in a ``finally`` block so they are cleaned up
whether the run succeeds or fails.

Error messages are routed to stderr using the ``Error: [CATEGORY] message``
convention and the handler exits with a non-zero status via ``SystemExit`` on
failure.
"""

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from typing import List

from nf_ica_cli.config import AppConfig
from nf_ica_cli.diff_generator import generate_diffs
from nf_ica_cli.git_ops import clone_at_commit
from nf_ica_cli.patch_registrar import CollectedPatch, register_collected_patches
from nf_ica_cli.pipeline_exporter import export_pipeline_source


def _derive_workflow_identifier(repo_uri: str, config: AppConfig) -> str:
    """Derive a ``[a-zA-Z0-9_-]+`` workflow identifier for suggested patch names.

    The ``collect-all-patches`` command is not given a workflow name directly —
    only a repository URI. To provide a sensible prefix for the suggested patch
    names (see :func:`nf_ica_cli.patch_prompter.suggest_patch_name`, which
    requires the identifier to match ``[a-zA-Z0-9_-]+``), we:

    1. Look for a workflow in ``config.workflows`` whose ``repo_uri`` matches
       ``repo_uri`` and use its ``name`` when found.
    2. Otherwise fall back to the repository basename (the last path segment of
       the URI, with any trailing ``.git`` removed).

    The chosen value is then slugified: any character not matching
    ``[a-zA-Z0-9_-]`` is replaced with an underscore, consecutive underscores
    are collapsed, and leading/trailing underscores are trimmed. If nothing
    usable remains, ``"workflow"`` is used as a last-resort default so the
    prefix is always a valid identifier.

    Args:
        repo_uri: The ``--repo-uri`` value provided by the user.
        config: The loaded application configuration (used to match workflows).

    Returns:
        A non-empty string matching ``[a-zA-Z0-9_-]+`` suitable as a suggested
        patch name prefix.
    """
    identifier = None

    # 1. Prefer a configured workflow name whose repo_uri matches.
    for workflow in config.workflows:
        if workflow.repo_uri == repo_uri:
            identifier = workflow.name
            break

    # 2. Fall back to the repository basename derived from the URI.
    if not identifier:
        # Strip a trailing slash, take the last path segment, drop ".git".
        basename = repo_uri.rstrip("/").rsplit("/", 1)[-1]
        if basename.endswith(".git"):
            basename = basename[: -len(".git")]
        identifier = basename

    # Slugify to guarantee a [a-zA-Z0-9_-]+ identifier.
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", identifier)
    slug = re.sub(r"_+", "_", slug).strip("_")

    return slug or "workflow"


def _print_summary(results: List[CollectedPatch]) -> None:
    """Print the collect-all-patches summary to stdout.

    For every registered (non-skipped) patch, prints a single tab-separated
    ``name<TAB>path`` line where ``path`` is the content-addressed registry
    path ``patches/<md5sum>.txt`` (Requirement 6.1). After the per-patch lines,
    prints a final human-readable line reporting the number of new, reused, and
    skipped patches (Requirement 6.2).

    All output is written to stdout (Requirement 6.5); this helper never writes
    to stderr.

    The three counts are derived from ``results`` as:

    * ``new_count`` — ``is_new`` is ``True`` and ``was_skipped`` is ``False``.
    * ``reused_count`` — ``is_new`` is ``False`` and ``was_skipped`` is ``False``.
    * ``skipped_count`` — ``was_skipped`` is ``True``.

    Together these partition ``results`` so their sum equals ``len(results)``
    (see design Property 7).

    Args:
        results: The :class:`CollectedPatch` results returned by
            :func:`nf_ica_cli.patch_registrar.register_collected_patches`.
    """
    new_count = 0
    reused_count = 0
    skipped_count = 0

    for result in results:
        if result.was_skipped:
            skipped_count += 1
            continue

        # Registered (non-skipped) patch: emit one tab-separated line.
        registry_path = f"patches/{result.md5sum}.txt"
        print(f"{result.name}\t{registry_path}")

        if result.is_new:
            new_count += 1
        else:
            reused_count += 1

    print(
        f"Summary: {new_count} new, {reused_count} reused, "
        f"{skipped_count} skipped."
    )


def handle_collect_all_patches(
    args: dict, config: AppConfig, config_repo: Path
) -> None:
    """Handle the collect-all-patches subcommand.

    Flow:

    1. Extract ``--repo-uri``, ``--commit-id``, ``--project-id`` and
       ``--pipeline-id`` from ``args``.
    2. Fail fast if ``ICAV2_ACCESS_TOKEN`` is unset or empty, before any network
       calls (Requirements 2.x, 3.2, 7.1, 7.2).
    3. Create temporary directories for the clone and the pipeline export.
    4. Clone the source repository at the commit via
       :func:`nf_ica_cli.git_ops.clone_at_commit`.
    5. Export the pipeline source via
       :func:`nf_ica_cli.pipeline_exporter.export_pipeline_source`.
    6. Generate diffs via :func:`nf_ica_cli.diff_generator.generate_diffs`; if
       there are none, print a no-patches message to stdout and return with a
       status of 0 (Requirement 6.3).
    7. Register the diffs via
       :func:`nf_ica_cli.patch_registrar.register_collected_patches` (which
       prompts the user and appends to ``patches.yaml`` itself).

    Both temporary directories are removed in a ``finally`` block using
    ``shutil.rmtree(..., ignore_errors=True)``. If removal reports a problem, a
    warning is logged to stderr and execution continues (Requirements 2.4, 3.6).

    Note:
        ``clone_at_commit`` does not currently support a clone timeout, so the
        300-second timeout mandated by Requirements 2.1/2.5 is not enforced
        here. Clone failures are surfaced clearly instead. See the task report.

    Args:
        args: Parsed docopt arguments dict.
        config: Loaded and validated application configuration.
        config_repo: Path to the configuration repository root.

    Raises:
        SystemExit: On a missing token, clone failure, or pipeline export
            failure, with a non-zero status code.
    """
    # 1. Extract arguments.
    repo_uri: str = args["--repo-uri"]
    commit_id: str = args["--commit-id"]
    project_id: str = args["--project-id"]
    pipeline_id: str = args["--pipeline-id"]

    # 2. Fail fast if the ICA access token is missing, before any network call
    #    (Requirements 3.2, 7.1, 7.2).
    access_token = os.environ.get("ICAV2_ACCESS_TOKEN")
    if not access_token:
        raise SystemExit(
            "Error: [AUTH] ICAV2_ACCESS_TOKEN environment variable is not set "
            "or is empty. Set ICAV2_ACCESS_TOKEN to a valid ICA access token "
            "before running collect-all-patches."
        )

    workflow_identifier = _derive_workflow_identifier(repo_uri, config)

    # 3. Create temporary directories for the clone and the export.
    clone_dir = Path(tempfile.mkdtemp(prefix="nf-ica-collect-clone-"))
    export_dir = Path(tempfile.mkdtemp(prefix="nf-ica-collect-export-"))

    try:
        # 4. Clone the source repository at the commit.
        #    NOTE: clone_at_commit has no timeout support; the 300s timeout
        #    (Req 2.1/2.5) is not enforced here. Surface failures clearly.
        try:
            clone_at_commit(repo_uri, commit_id, clone_dir)
        except RuntimeError as e:
            raise SystemExit(
                f"Error: [GIT] Failed to clone repository '{repo_uri}' at "
                f"commit '{commit_id}': {e}"
            ) from e

        # 5. Export the ICA pipeline source. export_pipeline_source raises
        #    RuntimeError with [AUTH]/[ICA API] context on failure.
        try:
            export_pipeline_source(
                project_id=project_id,
                pipeline_id=pipeline_id,
                output_dir=export_dir,
            )
        except RuntimeError as e:
            raise SystemExit(str(e)) from e

        # 6. Generate diffs between the two trees.
        diffs = generate_diffs(clone_dir, export_dir)

        if not diffs:
            # No differences found (Requirement 6.3): report and exit 0.
            print(
                "No patches generated: the source repository and the ICA "
                "pipeline source are identical."
            )
            return

        # 7. Register the diffs. register_collected_patches prompts the user
        #    and appends registered entries to patches.yaml itself, so the
        #    handler must NOT append to patches.yaml again.
        results = register_collected_patches(
            diffs=diffs,
            workflow_identifier=workflow_identifier,
            config_repo=config_repo,
            existing_patches=config.patches,
        )

        # Print the summary to stdout: one tab-separated name<TAB>path line per
        # registered patch, followed by a counts line (Requirements 6.1, 6.2,
        # 6.5). Factored into a helper so task 9.3's property test can target
        # the summary logic (design Property 7).
        _print_summary(results)
    finally:
        # Clean up both temp directories, warning to stderr on failure
        # (Requirements 2.4, 3.6).
        for temp_dir in (clone_dir, export_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                if temp_dir.exists():
                    print(
                        f"Warning: [CLEANUP] Failed to remove temporary "
                        f"directory '{temp_dir}'.",
                        file=sys.stderr,
                    )
            except OSError as e:
                print(
                    f"Warning: [CLEANUP] Failed to remove temporary directory "
                    f"'{temp_dir}': {e}.",
                    file=sys.stderr,
                )
