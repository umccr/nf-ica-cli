"""Property-based tests for release status transitions.

Tests Properties 10-11 from the design document using Hypothesis.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.config import AppConfig, IcaConfig, PipelineEntry, Tenant
from nf_ica_cli.handlers.update_release_status import handle_update_release_status
from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.yaml_io import load_yaml


# --- Strategies ---

# Valid workflow names: non-empty alphanumeric with hyphens/underscores
workflow_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=30,
)

# Valid version tags
version_tags = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789.",
    min_size=1,
    max_size=20,
)

# Valid git commit IDs (7-40 hex chars)
git_commit_ids = st.text(
    alphabet="abcdef0123456789",
    min_size=7,
    max_size=40,
)

# Valid pipeline IDs (UUID-like)
pipeline_ids = st.text(
    alphabet="abcdef0123456789-",
    min_size=10,
    max_size=36,
)

# Context names
context_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=20,
)

# Nextflow versions
nextflow_versions = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)


def _create_pipelines_yaml(tmp_dir: Path, pipeline_entry: dict) -> Path:
    """Create a minimal ica_pipelines.yaml file for testing.

    Args:
        tmp_dir: Temporary directory acting as config repo.
        pipeline_entry: Dict representing a pipeline entry.

    Returns:
        Path to the ica_pipelines.yaml file.
    """
    config_dir = tmp_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    pipelines_path = config_dir / "ica_pipelines.yaml"
    # Use ruamel.yaml to write so we can read it back properly
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True
    data = {"pipelines": [pipeline_entry]}
    with open(pipelines_path, "w") as f:
        yaml.dump(data, f)

    return pipelines_path


def _build_app_config(
    tmp_dir: Path,
    workflow_name: str,
    workflow_version: str,
    git_commit_id: str,
    pipeline_id: str,
    release_status: str,
    contexts: list,
    ica_nextflow_version: str,
) -> AppConfig:
    """Build an AppConfig with a single pipeline entry for testing."""
    pipeline = PipelineEntry(
        workflow_name=workflow_name,
        workflow_version=workflow_version,
        git_commit_id=git_commit_id,
        pipeline_id=pipeline_id,
        release_status=release_status,
        tenants=["test-tenant"],
        contexts=contexts,
        patch_files=[],
        ica_nextflow_version=ica_nextflow_version,
    )

    return AppConfig(
        config_repo=tmp_dir,
        workflows=[],
        contexts=[],
        ica_config=IcaConfig(tenants=[], default_nextflow_version=""),
        pipelines=[pipeline],
        patches=[],
    )


# --- Property 10: Release status transition irreversibility ---
# Feature: nf-ica-cli, Property 10: For any pipeline entry with release_status equal to
# "RELEASED", attempting to update the status to "DRAFT" SHALL be rejected with an error.


class TestReleaseStatusTransitionIrreversibility:
    """**Validates: Requirements 4.4**"""

    @given(
        workflow_name=workflow_names,
        version_tag=version_tags,
        git_commit_id=git_commit_ids,
        pipeline_id=pipeline_ids,
        context=context_names,
        nf_version=nextflow_versions,
    )
    @settings(max_examples=100)
    def test_released_to_draft_is_always_rejected(
        self,
        workflow_name: str,
        version_tag: str,
        git_commit_id: str,
        pipeline_id: str,
        context: str,
        nf_version: str,
    ) -> None:
        """Attempting to transition from RELEASED to DRAFT always raises SystemExit.

        For any pipeline entry that is already RELEASED, requesting a status
        change to DRAFT SHALL be rejected with an error (SystemExit).
        """
        # Feature: nf-ica-cli, Property 10: Release status transition irreversibility
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Create the pipeline entry with RELEASED status
            entry_dict = {
                "workflow_name": workflow_name,
                "workflow_version": version_tag,
                "git_commit_id": git_commit_id,
                "pipeline_id": pipeline_id,
                "release_status": "RELEASED",
                "tenants": ["test-tenant"],
                "contexts": [context],
                "patch_files": [],
                "ica_nextflow_version": nf_version,
            }
            _create_pipelines_yaml(tmp_dir, entry_dict)

            config = _build_app_config(
                tmp_dir=tmp_dir,
                workflow_name=workflow_name,
                workflow_version=version_tag,
                git_commit_id=git_commit_id,
                pipeline_id=pipeline_id,
                release_status="RELEASED",
                contexts=[context],
                ica_nextflow_version=nf_version,
            )

            # Build args dict simulating docopt output
            args = {
                "--workflow-name": workflow_name,
                "--workflow-version-tag": version_tag,
                "--release-status": "DRAFT",
            }

            # Attempting RELEASED → DRAFT must always raise SystemExit
            with pytest.raises(SystemExit) as exc_info:
                handle_update_release_status(args, config, tmp_dir)

            # Verify it's an error exit (non-zero or error message)
            error_msg = str(exc_info.value)
            assert "RELEASED" in error_msg or "STATE VIOLATION" in error_msg

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Property 11: Status update idempotence ---
# Feature: nf-ica-cli, Property 11: For any pipeline entry, updating the release status
# to the value it already holds SHALL produce no changes to the YAML file and SHALL
# return a zero exit code.


class TestStatusUpdateIdempotence:
    """**Validates: Requirements 4.5**"""

    @given(
        workflow_name=workflow_names,
        version_tag=version_tags,
        git_commit_id=git_commit_ids,
        pipeline_id=pipeline_ids,
        release_status=st.sampled_from(["DRAFT", "RELEASED"]),
        context=context_names,
        nf_version=nextflow_versions,
    )
    @settings(max_examples=100)
    def test_same_status_update_is_noop(
        self,
        workflow_name: str,
        version_tag: str,
        git_commit_id: str,
        pipeline_id: str,
        release_status: str,
        context: str,
        nf_version: str,
    ) -> None:
        """Updating status to the same value produces no file changes and exits 0.

        For any pipeline entry with a given release_status, requesting an update
        to that same status SHALL exit with code 0 and SHALL NOT modify the YAML.
        """
        # Feature: nf-ica-cli, Property 11: Status update idempotence
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Create the pipeline entry with the given status
            entry_dict = {
                "workflow_name": workflow_name,
                "workflow_version": version_tag,
                "git_commit_id": git_commit_id,
                "pipeline_id": pipeline_id,
                "release_status": release_status,
                "tenants": ["test-tenant"],
                "contexts": [context],
                "patch_files": [],
                "ica_nextflow_version": nf_version,
            }
            pipelines_path = _create_pipelines_yaml(tmp_dir, entry_dict)

            # Read the file content before the operation
            content_before = pipelines_path.read_text()

            config = _build_app_config(
                tmp_dir=tmp_dir,
                workflow_name=workflow_name,
                workflow_version=version_tag,
                git_commit_id=git_commit_id,
                pipeline_id=pipeline_id,
                release_status=release_status,
                contexts=[context],
                ica_nextflow_version=nf_version,
            )

            # Build args dict simulating docopt output
            args = {
                "--workflow-name": workflow_name,
                "--workflow-version-tag": version_tag,
                "--release-status": release_status,
            }

            # Same-status update must exit with code 0
            with pytest.raises(SystemExit) as exc_info:
                handle_update_release_status(args, config, tmp_dir)

            assert exc_info.value.code == 0

            # Verify the YAML file was NOT modified
            content_after = pipelines_path.read_text()
            assert content_before == content_after

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
