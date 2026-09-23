"""nf-ica CLI — Nextflow ICA pipeline orchestration.

Usage:
    nf-ica <command> [<args>...]
    nf-ica -h | --help
    nf-ica --version

Commands:
    register-patch                          Register a patch file for use in deployments
    add-workflow-version                    Add a new workflow version to workflows.yaml
    deploy-workflow-version                 Create an annotated git tag for deployment
    update-workflow-version-release-status  Update release status of a pipeline entry
    gh-actions-deploy-workflow              Deploy a workflow version to ICA projects
    collect-all-patches                     Collect patches from an ICA pipeline by diffing against source

Options:
    -h --help     Show this help message
    --version     Show version

See 'nf-ica <command> --help' for details on a specific command.
"""

import sys

_SUBCMD_USAGE = {
    "register-patch": """Register a patch file for use in deployments.

Usage:
    nf-ica register-patch
        (--file=<path>)
        (--name=<name>)
        (--description=<desc>)

Options:
    --file=<path>         Path to the patch file to register
    --name=<name>         Unique name for the patch
    --description=<desc>  Short description of what the patch does
    -h --help             Show this help message
""",
    "add-workflow-version": """Add a new workflow version to workflows.yaml.

Usage:
    nf-ica add-workflow-version
        (--workflow-name=<name>)
        (--workflow-repo-uri=<uri>)
        (--workflow-version-tag=<tag>)
        (--workflow-version-git-commit-id=<id>)
        (--workflow-version-context=<ctx>...)
        (--workflow-ica-nextflow-version=<ver>)

Options:
    --workflow-name=<name>                   Name of the workflow
    --workflow-repo-uri=<uri>                Git repository URI for the workflow
    --workflow-version-tag=<tag>             Version tag (e.g. 1.0.0)
    --workflow-version-git-commit-id=<id>    Full git commit SHA for this version
    --workflow-version-context=<ctx>         Deployment context(s) (repeatable)
    --workflow-ica-nextflow-version=<ver>    ICA Nextflow engine version to use
    -h --help                                Show this help message
""",
    "deploy-workflow-version": """Create an annotated git tag encoding deployment metadata.

Usage:
    nf-ica deploy-workflow-version
        (--workflow-name=<name>)
        (--workflow-version-tag=<tag>)
        (--workflow-version-git-commit-id=<id>)
        (--workflow-version-context=<ctx>...)
        [--workflow-patch-name=<patch>...]
        (--release-status=<status>)
        [--workflow-version-description=<desc>]

Options:
    --workflow-name=<name>                   Name of the workflow
    --workflow-version-tag=<tag>             Registered version tag to deploy
    --workflow-version-git-commit-id=<id>    Full git commit SHA
    --workflow-version-context=<ctx>         Deployment context(s) (repeatable)
    --workflow-patch-name=<patch>            Patch name(s) to apply (repeatable, optional)
    --release-status=<status>               Release status (DRAFT or RELEASED)
    --workflow-version-description=<desc>    Optional description for the version
    -h --help                                Show this help message
""",
    "update-workflow-version-release-status": """Update release status of a pipeline entry.

Usage:
    nf-ica update-workflow-version-release-status
        (--workflow-name=<name>)
        (--workflow-version-tag=<tag>)
        (--release-status=<status>)

Options:
    --workflow-name=<name>         Name of the workflow
    --workflow-version-tag=<tag>   Version tag of the pipeline entry
    --release-status=<status>     New release status (DRAFT or RELEASED)
    -h --help                      Show this help message
""",
    "gh-actions-deploy-workflow": """Deploy a workflow version to ICA projects.

Usage:
    nf-ica gh-actions-deploy-workflow
        (--workflow-name=<name>)
        (--workflow-version=<ver>)
        (--annotated-tag-name=<tag>)

Options:
    --workflow-name=<name>         Name of the workflow to deploy
    --workflow-version=<ver>       Workflow version to deploy
    --annotated-tag-name=<tag>    Name of the annotated git tag with metadata
    -h --help                      Show this help message
""",
    "collect-all-patches": """Collect patches from an ICA pipeline by diffing against source.

Usage:
    nf-ica collect-all-patches
        (--repo-uri=<uri>)
        (--commit-id=<id>)
        (--project-id=<pid>)
        (--pipeline-id=<plid>)

Options:
    --repo-uri=<uri>       Git repository URI for the original workflow source
    --commit-id=<id>       Git commit SHA to compare against
    --project-id=<pid>     ICA project UUID containing the pipeline
    --pipeline-id=<plid>   ICA pipeline UUID to export source from
    -h --help              Show this help message
""",
}


def main() -> None:
    """Entry point for the nf-ica CLI.

    Uses a two-pass docopt parsing approach:
    1. First pass: identify the subcommand (options_first=True)
    2. Second pass: parse the subcommand's own usage for full argument handling

    This enables per-subcommand --help output.

    Heavy imports (wrapica, boto3, handlers) are deferred until after argument
    parsing confirms a subcommand is needed, keeping --help and --version fast.

    All unhandled exceptions are caught and formatted as error messages with
    a non-zero exit code.
    """
    from docopt import docopt

    try:
        # First pass: identify the subcommand
        # --help and --version exit here without touching heavy imports
        top_args = docopt(__doc__, version="nf-ica-cli 0.1.0", options_first=True)

        command = top_args["<command>"]
        argv = [command] + top_args["<args>"]

        if command not in _SUBCMD_USAGE:
            print(f"Error: Unknown command '{command}'.", file=sys.stderr)
            print("See 'nf-ica --help' for available commands.", file=sys.stderr)
            sys.exit(1)

        # Second pass: parse with the subcommand's own usage string
        # Per-subcommand --help exits here, still no heavy imports
        args = docopt(_SUBCMD_USAGE[command], argv=argv)

        # Now that we know we need to execute a command, import heavy deps
        from nf_ica_cli.config import find_config_repo, load_and_validate_config

        # Locate the config repo by traversing upward from CWD
        config_repo = find_config_repo()

        # Load and validate all configuration files
        config = load_and_validate_config(config_repo)

        # Dispatch to the appropriate subcommand handler with lazy imports
        if command == "register-patch":
            from nf_ica_cli.handlers.register_patch import handle_register_patch

            handle_register_patch(args, config, config_repo)
        elif command == "add-workflow-version":
            from nf_ica_cli.handlers.add_workflow_version import (
                handle_add_workflow_version,
            )

            handle_add_workflow_version(args, config, config_repo)
        elif command == "deploy-workflow-version":
            from nf_ica_cli.handlers.deploy_workflow_version import (
                handle_deploy_workflow_version,
            )

            handle_deploy_workflow_version(args, config, config_repo)
        elif command == "update-workflow-version-release-status":
            from nf_ica_cli.handlers.update_release_status import (
                handle_update_release_status,
            )

            handle_update_release_status(args, config, config_repo)
        elif command == "gh-actions-deploy-workflow":
            from nf_ica_cli.handlers.deploy_workflow import handle_deploy_workflow

            handle_deploy_workflow(args, config, config_repo)
        elif command == "collect-all-patches":
            from nf_ica_cli.handlers.collect_all_patches import (
                handle_collect_all_patches,
            )

            handle_collect_all_patches(args, config, config_repo)

    except SystemExit as e:
        # SystemExit from docopt (--help, --version) or our own validation
        # Re-raise to let Python handle exit codes properly
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        # Catch any unhandled exceptions and format as error message
        print(f"Error: [UNEXPECTED] {e}", file=sys.stderr)
        sys.exit(1)
