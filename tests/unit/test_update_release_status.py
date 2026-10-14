"""Unit tests for the update-workflow-version-release-status handler."""

from pathlib import Path

import pytest

from nf_ica_cli.config import AppConfig, IcaConfig, PipelineEntry
from nf_ica_cli.handlers.update_release_status import handle_update_release_status
from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.yaml_io import load_yaml, save_yaml


def _make_pipeline_entry(
    workflow_name: str = "oncoanalyser",
    workflow_version: str = "2.2.0",
    release_status: str = "DRAFT",
    patch_files: list = None,
) -> PipelineEntry:
    """Create a PipelineEntry for testing."""
    return PipelineEntry(
        workflow_name=workflow_name,
        workflow_version=workflow_version,
        git_commit_id="abc1234",
        pipeline_id="pipeline-uuid-123",
        release_status=release_status,
        tenants=["umccr-prod"],
        contexts=["production"],
        patch_files=patch_files or [],
        ica_nextflow_version="25.10",
    )


def _make_app_config(
    config_repo: Path,
    pipelines: list = None,
    patches: list = None,
) -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        config_repo=config_repo,
        workflows=[],
        contexts=[],
        ica_config=IcaConfig(tenants=[], default_nextflow_version=""),
        pipelines=pipelines or [],
        patches=patches or [],
    )


def _make_args(
    workflow_name: str = "oncoanalyser",
    version_tag: str = "2.2.0",
    release_status: str = "RELEASED",
) -> dict:
    """Create a minimal docopt-style args dict for update-release-status."""
    return {
        "--workflow-name": workflow_name,
        "--workflow-version-tag": version_tag,
        "--release-status": release_status,
        "update-workflow-version-release-status": True,
    }


def _setup_pipelines_yaml(config_repo: Path, pipelines_list: list) -> Path:
    """Create ica_pipelines.yaml with given pipeline entries."""
    config_dir = config_repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    pipelines_path = config_dir / "ica_pipelines.yaml"
    data = {"pipelines": pipelines_list}
    save_yaml(pipelines_path, data)
    return pipelines_path


class TestHandleUpdateReleaseStatus:
    """Tests for handle_update_release_status handler."""

    def test_updates_draft_to_released(self, tmp_path):
        """Successfully transitions DRAFT → RELEASED and writes YAML."""
        config_repo = tmp_path / "config_repo"
        pipelines_path = _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            }
        ])

        pipeline = _make_pipeline_entry(release_status="DRAFT")
        config = _make_app_config(config_repo, pipelines=[pipeline])
        args = _make_args(release_status="RELEASED")

        handle_update_release_status(args, config, config_repo)

        # Verify the YAML was updated
        data = load_yaml(pipelines_path)
        assert data["pipelines"][0]["release_status"] == "RELEASED"

    def test_exits_when_pipeline_not_found(self, tmp_path):
        """Exits with SystemExit when no matching pipeline entry exists (Req 4.2)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo, [])

        config = _make_app_config(config_repo, pipelines=[])
        args = _make_args(workflow_name="nonexistent", version_tag="1.0.0")

        with pytest.raises(SystemExit, match="No pipeline entry found"):
            handle_update_release_status(args, config, config_repo)

    def test_exits_on_invalid_release_status(self, tmp_path):
        """Exits with SystemExit for invalid release status value (Req 4.3)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo, [])

        config = _make_app_config(config_repo)
        args = _make_args(release_status="INVALID")

        with pytest.raises(SystemExit, match="Invalid release status"):
            handle_update_release_status(args, config, config_repo)

    def test_rejects_released_to_draft_transition(self, tmp_path):
        """Exits with SystemExit when reverting RELEASED → DRAFT (Req 4.4)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "RELEASED",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            }
        ])

        pipeline = _make_pipeline_entry(release_status="RELEASED")
        config = _make_app_config(config_repo, pipelines=[pipeline])
        args = _make_args(release_status="DRAFT")

        with pytest.raises(SystemExit, match="Cannot revert release status"):
            handle_update_release_status(args, config, config_repo)

    def test_noop_when_status_unchanged(self, tmp_path):
        """Exits with code 0 without modifying YAML when status is same (Req 4.5)."""
        config_repo = tmp_path / "config_repo"
        pipelines_path = _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            }
        ])

        pipeline = _make_pipeline_entry(release_status="DRAFT")
        config = _make_app_config(config_repo, pipelines=[pipeline])
        args = _make_args(release_status="DRAFT")

        with pytest.raises(SystemExit) as exc_info:
            handle_update_release_status(args, config, config_repo)

        # sys.exit(0) raises SystemExit with code 0
        assert exc_info.value.code == 0

    def test_verifies_patches_registered_when_releasing(self, tmp_path):
        """Exits when releasing and a patch is not registered (Req 4.6)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": ["missing-patch"],
                "ica_nextflow_version": "25.10",
            }
        ])

        pipeline = _make_pipeline_entry(
            release_status="DRAFT",
            patch_files=["missing-patch"],
        )
        config = _make_app_config(config_repo, pipelines=[pipeline], patches=[])
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="not registered"):
            handle_update_release_status(args, config, config_repo)

    def test_verifies_patch_file_exists_on_disk_when_releasing(self, tmp_path):
        """Exits when releasing and patch file doesn't exist on disk (Req 4.6)."""
        config_repo = tmp_path / "config_repo"
        (config_repo / "config").mkdir(parents=True)
        (config_repo / "patches").mkdir(parents=True)

        _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": ["my-patch"],
                "ica_nextflow_version": "25.10",
            }
        ])

        # Patch is registered but file doesn't exist on disk
        patch = PatchEntry(
            name="my-patch",
            path="patches/abc123.txt",
            md5sum="abc123",
            description="A patch",
        )

        pipeline = _make_pipeline_entry(
            release_status="DRAFT",
            patch_files=["my-patch"],
        )
        config = _make_app_config(
            config_repo, pipelines=[pipeline], patches=[patch]
        )
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit, match="Patch file missing"):
            handle_update_release_status(args, config, config_repo)

    def test_releases_successfully_with_valid_patches(self, tmp_path):
        """Successfully releases when all patches are registered and exist."""
        config_repo = tmp_path / "config_repo"
        (config_repo / "config").mkdir(parents=True)
        (config_repo / "patches").mkdir(parents=True)

        # Create the patch file on disk
        patch_file = config_repo / "patches" / "abc123.txt"
        patch_file.write_text("patch content")

        pipelines_path = _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": ["my-patch"],
                "ica_nextflow_version": "25.10",
            }
        ])

        patch = PatchEntry(
            name="my-patch",
            path="patches/abc123.txt",
            md5sum="abc123",
            description="A patch",
        )
        pipeline = _make_pipeline_entry(
            release_status="DRAFT",
            patch_files=["my-patch"],
        )
        config = _make_app_config(
            config_repo, pipelines=[pipeline], patches=[patch]
        )
        args = _make_args(release_status="RELEASED")

        handle_update_release_status(args, config, config_repo)

        # Verify the YAML was updated
        data = load_yaml(pipelines_path)
        assert data["pipelines"][0]["release_status"] == "RELEASED"

    def test_preserves_yaml_comments(self, tmp_path):
        """YAML comments are preserved after status update (Req 4.7)."""
        config_repo = tmp_path / "config_repo"
        config_dir = config_repo / "config"
        config_dir.mkdir(parents=True)

        # Write YAML with a comment
        pipelines_path = config_dir / "ica_pipelines.yaml"
        pipelines_path.write_text(
            "# This is a tracking file for deployed pipelines\n"
            "pipelines:\n"
            "  - workflow_name: oncoanalyser\n"
            "    workflow_version: '2.2.0'\n"
            "    git_commit_id: abc1234\n"
            "    pipeline_id: pipeline-uuid-123\n"
            "    release_status: DRAFT\n"
            "    tenants:\n"
            "      - umccr-prod\n"
            "    contexts:\n"
            "      - production\n"
            "    patch_files: []\n"
            "    ica_nextflow_version: '25.10'\n"
        )

        pipeline = _make_pipeline_entry(release_status="DRAFT")
        config = _make_app_config(config_repo, pipelines=[pipeline])
        args = _make_args(release_status="RELEASED")

        handle_update_release_status(args, config, config_repo)

        # Read raw content and verify comment is preserved
        raw_content = pipelines_path.read_text()
        assert "# This is a tracking file for deployed pipelines" in raw_content
        assert "RELEASED" in raw_content

    def test_updates_correct_entry_among_multiple(self, tmp_path):
        """Updates only the matching entry when multiple pipelines exist."""
        config_repo = tmp_path / "config_repo"
        pipelines_path = _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "pipeline-a",
                "workflow_version": "1.0.0",
                "git_commit_id": "aaa1111",
                "pipeline_id": "uuid-a",
                "release_status": "DRAFT",
                "tenants": ["tenant-1"],
                "contexts": ["dev"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            },
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "uuid-b",
                "release_status": "DRAFT",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            },
        ])

        # Only the second one matches
        pipelines = [
            _make_pipeline_entry(
                workflow_name="pipeline-a",
                workflow_version="1.0.0",
                release_status="DRAFT",
            ),
            _make_pipeline_entry(
                workflow_name="oncoanalyser",
                workflow_version="2.2.0",
                release_status="DRAFT",
            ),
        ]
        config = _make_app_config(config_repo, pipelines=pipelines)
        args = _make_args(
            workflow_name="oncoanalyser",
            version_tag="2.2.0",
            release_status="RELEASED",
        )

        handle_update_release_status(args, config, config_repo)

        data = load_yaml(pipelines_path)
        # First pipeline unchanged
        assert data["pipelines"][0]["release_status"] == "DRAFT"
        # Second pipeline updated
        assert data["pipelines"][1]["release_status"] == "RELEASED"

    def test_noop_released_to_released(self, tmp_path):
        """No-op when current and new status are both RELEASED (Req 4.5)."""
        config_repo = tmp_path / "config_repo"
        _setup_pipelines_yaml(config_repo, [
            {
                "workflow_name": "oncoanalyser",
                "workflow_version": "2.2.0",
                "git_commit_id": "abc1234",
                "pipeline_id": "pipeline-uuid-123",
                "release_status": "RELEASED",
                "tenants": ["umccr-prod"],
                "contexts": ["production"],
                "patch_files": [],
                "ica_nextflow_version": "25.10",
            }
        ])

        pipeline = _make_pipeline_entry(release_status="RELEASED")
        config = _make_app_config(config_repo, pipelines=[pipeline])
        args = _make_args(release_status="RELEASED")

        with pytest.raises(SystemExit) as exc_info:
            handle_update_release_status(args, config, config_repo)

        assert exc_info.value.code == 0
