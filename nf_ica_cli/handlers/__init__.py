"""Subcommand handlers for nf-ica CLI."""

from nf_ica_cli.handlers.add_workflow_version import handle_add_workflow_version
from nf_ica_cli.handlers.deploy_workflow import handle_deploy_workflow
from nf_ica_cli.handlers.deploy_workflow_version import handle_deploy_workflow_version
from nf_ica_cli.handlers.register_patch import handle_register_patch
from nf_ica_cli.handlers.update_release_status import handle_update_release_status

__all__ = [
    "handle_add_workflow_version",
    "handle_deploy_workflow",
    "handle_deploy_workflow_version",
    "handle_register_patch",
    "handle_update_release_status",
]
