"""Unit tests for release page generator."""

import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.release_page import (
    DeploymentResult,
    generate_release_body,
    create_pipeline_zip,
    create_github_release,
    update_github_release,
)


class TestDeploymentResult:
    """Tests for the DeploymentResult dataclass."""

    def test_create_deployment_result(self):
        result = DeploymentResult(
            project_name="my-project",
            project_id="proj-123",
            tenant_name="my-tenant",
            pipeline_id="pipe-456",
            contexts=["development", "production"],
        )
        assert result.project_name == "my-project"
        assert result.project_id == "proj-123"
        assert result.tenant_name == "my-tenant"
        assert result.pipeline_id == "pipe-456"
        assert result.contexts == ["development", "production"]


class TestGenerateReleaseBody:
    """Tests for the generate_release_body function."""

    def _make_deployments(self):
        return [
            DeploymentResult(
                project_name="project-alpha",
                project_id="proj-aaa",
                tenant_name="tenant-one",
                pipeline_id="pipe-111",
                contexts=["development"],
            ),
            DeploymentResult(
                project_name="project-beta",
                project_id="proj-bbb",
                tenant_name="tenant-two",
                pipeline_id="pipe-222",
                contexts=["production", "staging"],
            ),
        ]

    def test_basic_release_body_contains_header(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "# oncoanalyser v2.2.0" in body

    def test_release_body_contains_commit_id(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234def5678",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "`abc1234def5678`" in body

    def test_release_body_contains_description_when_provided(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="Bug fix for memory issue",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "Bug fix for memory issue" in body
        assert "**Description:**" in body

    def test_release_body_omits_description_when_empty(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "**Description:**" not in body

    def test_release_body_contains_release_status(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="RELEASED",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "**Release Status:** RELEASED" in body

    def test_release_body_contains_nextflow_version(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "**Nextflow Version:** 23.10.0" in body

    def test_release_body_contains_deployment_table(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        # Check table headers
        assert "| Project" in body
        assert "| Tenant" in body
        assert "| Pipeline ID" in body
        assert "| Contexts" in body
        # Check table data
        assert "project-alpha" in body
        assert "tenant-one" in body
        assert "`pipe-111`" in body
        assert "development" in body
        assert "project-beta" in body
        assert "production, staging" in body

    def test_release_body_contains_patches_section(self):
        patches = [
            PatchEntry(
                name="fix-memory",
                path="patches/aaaa1111bbbb2222cccc3333dddd4444.txt",
                md5sum="aaaa1111bbbb2222cccc3333dddd4444",
                description="Fix memory allocation",
            ),
            PatchEntry(
                name="add-retry",
                path="patches/eeee5555ffff6666gggg7777hhhh8888.txt",
                md5sum="eeee5555ffff6666gggg7777hhhh8888",
                description="Add retry logic",
            ),
        ]
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=patches,
            patch_base_url="https://github.com/umccr/nf-ica/blob/deadbeef",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "## Applied Patches" in body
        # Table headers
        assert "| Name" in body
        assert "| URL" in body
        assert "| MD5sum" in body
        assert "| Description" in body
        # Patch names
        assert "fix-memory" in body
        assert "add-retry" in body
        # Permalink URLs built from base + repo-relative path
        assert (
            "https://github.com/umccr/nf-ica/blob/deadbeef/"
            "patches/aaaa1111bbbb2222cccc3333dddd4444.txt"
        ) in body
        assert (
            "https://github.com/umccr/nf-ica/blob/deadbeef/"
            "patches/eeee5555ffff6666gggg7777hhhh8888.txt"
        ) in body
        # md5sums and descriptions
        assert "`aaaa1111bbbb2222cccc3333dddd4444`" in body
        assert "Fix memory allocation" in body
        assert "Add retry logic" in body

    def test_release_body_omits_patches_section_when_empty(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "Applied Patches" not in body

    def test_release_body_contains_skipped_projects_section(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=["project-gamma", "project-delta"],
        )
        assert "## Skipped Projects (Auth Failure)" in body
        assert "- project-gamma" in body
        assert "- project-delta" in body

    def test_release_body_omits_skipped_section_when_empty(self):
        body = generate_release_body(
            workflow_name="oncoanalyser",
            workflow_version="2.2.0",
            git_commit_id="abc1234",
            workflow_version_description="",
            release_status="DRAFT",
            nextflow_version="23.10.0",
            patches=[],
            patch_base_url="",
            deployments=self._make_deployments(),
            skipped_projects=[],
        )
        assert "Skipped Projects" not in body


class TestCreatePipelineZip:
    """Tests for the create_pipeline_zip function."""

    def test_creates_zip_with_files(self, tmp_path):
        # Create a source directory with files
        source_dir = tmp_path / "pipeline_source"
        source_dir.mkdir()
        (source_dir / "main.nf").write_text("workflow { println 'hello' }")
        (source_dir / "nextflow.config").write_text("params { input = '' }")
        sub_dir = source_dir / "modules"
        sub_dir.mkdir()
        (sub_dir / "module1.nf").write_text("process FOO { }")

        output_path = tmp_path / "pipeline.zip"
        result = create_pipeline_zip(source_dir, output_path)

        assert result == output_path
        assert output_path.exists()

        # Verify zip contents
        with zipfile.ZipFile(output_path, "r") as zf:
            names = sorted(zf.namelist())
            assert "main.nf" in names
            assert "nextflow.config" in names
            assert "modules/module1.nf" in names

    def test_zip_preserves_file_contents(self, tmp_path):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        content = "workflow { println 'test content' }"
        (source_dir / "main.nf").write_text(content)

        output_path = tmp_path / "output.zip"
        create_pipeline_zip(source_dir, output_path)

        with zipfile.ZipFile(output_path, "r") as zf:
            assert zf.read("main.nf").decode() == content

    def test_zip_handles_empty_directory(self, tmp_path):
        source_dir = tmp_path / "empty_source"
        source_dir.mkdir()

        output_path = tmp_path / "empty.zip"
        result = create_pipeline_zip(source_dir, output_path)

        assert result == output_path
        assert output_path.exists()

        with zipfile.ZipFile(output_path, "r") as zf:
            assert zf.namelist() == []

    def test_zip_excludes_directories_as_entries(self, tmp_path):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        sub = source_dir / "subdir"
        sub.mkdir()
        (sub / "file.txt").write_text("content")

        output_path = tmp_path / "test.zip"
        create_pipeline_zip(source_dir, output_path)

        with zipfile.ZipFile(output_path, "r") as zf:
            # Only files should be in the zip, not directory entries
            for name in zf.namelist():
                assert not name.endswith("/")


class TestCreateGithubRelease:
    """Tests for the create_github_release function."""

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_calls_gh_with_correct_args(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="oncoanalyser/2.2.0__20250715143022",
            release_body="# Release notes",
            artefact_paths=[Path("/tmp/pipeline.zip")],
        )

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]

        assert cmd[0] == "gh"
        assert cmd[1] == "release"
        assert cmd[2] == "create"
        assert cmd[3] == "oncoanalyser/2.2.0__20250715143022"
        assert cmd[4] == "--title"
        assert cmd[5] == "oncoanalyser/2.2.0__20250715143022"
        assert cmd[6] == "--notes"
        assert cmd[7] == "# Release notes"
        assert cmd[8] == "/tmp/pipeline.zip"

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_adds_draft_flag_when_draft_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="oncoanalyser/2.2.0__20250715143022",
            release_body="# Release notes",
            artefact_paths=[Path("/tmp/pipeline.zip")],
            draft=True,
        )

        cmd = mock_run.call_args[0][0]
        assert "--draft" in cmd
        # Artefact path still appended after the flag
        assert "/tmp/pipeline.zip" in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_omits_draft_flag_by_default(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="oncoanalyser/2.2.0__20250715143022",
            release_body="# Release notes",
            artefact_paths=[Path("/tmp/pipeline.zip")],
        )

        cmd = mock_run.call_args[0][0]
        assert "--draft" not in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_omits_draft_flag_when_draft_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="oncoanalyser/2.2.0__20250715143022",
            release_body="# Release notes",
            artefact_paths=[],
            draft=False,
        )

        cmd = mock_run.call_args[0][0]
        assert "--draft" not in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_handles_multiple_artefacts(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="workflow/1.0.0__20250101120000",
            release_body="body",
            artefact_paths=[Path("/tmp/a.zip"), Path("/tmp/b.zip")],
        )

        cmd = mock_run.call_args[0][0]
        assert "/tmp/a.zip" in cmd
        assert "/tmp/b.zip" in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_raises_runtime_error_on_failure(self, mock_run):
        import subprocess as sp

        mock_run.side_effect = sp.CalledProcessError(
            returncode=1,
            cmd=["gh", "release", "create"],
            stderr="release already exists",
        )

        with pytest.raises(RuntimeError, match="Failed to create release"):
            create_github_release(
                tag_name="workflow/1.0.0__20250101120000",
                release_body="body",
                artefact_paths=[],
            )

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_raises_runtime_error_when_gh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("No such file or directory: 'gh'")

        with pytest.raises(RuntimeError, match="'gh' CLI tool is not installed"):
            create_github_release(
                tag_name="workflow/1.0.0__20250101120000",
                release_body="body",
                artefact_paths=[],
            )

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_handles_empty_artefact_list(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        create_github_release(
            tag_name="workflow/1.0.0__20250101120000",
            release_body="body",
            artefact_paths=[],
        )

        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "gh",
            "release",
            "create",
            "workflow/1.0.0__20250101120000",
            "--title",
            "workflow/1.0.0__20250101120000",
            "--notes",
            "body",
        ]


class TestUpdateGithubRelease:
    """Tests for the update_github_release function."""

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_edits_notes_only_when_no_artefacts(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        update_github_release(
            tag_name="sash/0.6.5-rc__x",
            release_body="# notes",
            artefact_paths=[],
        )

        # Only the edit command runs.
        assert mock_run.call_count == 1
        cmd = mock_run.call_args_list[0][0][0]
        assert cmd[:4] == ["gh", "release", "edit", "sash/0.6.5-rc__x"]
        assert "--notes" in cmd
        assert "--draft=false" not in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_publish_clears_draft_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        update_github_release(
            tag_name="sash/0.6.5-rc__x",
            release_body="# notes",
            artefact_paths=[],
            publish=True,
        )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--draft=false" in cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_uploads_artefacts_with_clobber(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        update_github_release(
            tag_name="sash/0.6.5-rc__x",
            release_body="# notes",
            artefact_paths=[Path("/tmp/a.zip")],
        )

        assert mock_run.call_count == 2
        upload_cmd = mock_run.call_args_list[1][0][0]
        assert upload_cmd[:4] == ["gh", "release", "upload", "sash/0.6.5-rc__x"]
        assert "/tmp/a.zip" in upload_cmd
        assert "--clobber" in upload_cmd

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_raises_on_edit_failure(self, mock_run):
        import subprocess as sp

        mock_run.side_effect = sp.CalledProcessError(
            returncode=1,
            cmd=["gh", "release", "edit"],
            stderr="release not found",
        )

        with pytest.raises(RuntimeError, match="Failed to update release"):
            update_github_release(
                tag_name="sash/0.6.5-rc__x",
                release_body="# notes",
                artefact_paths=[],
            )

    @patch("nf_ica_cli.release_page.subprocess.run")
    def test_raises_when_gh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gh missing")

        with pytest.raises(RuntimeError, match="'gh' CLI tool is not installed"):
            update_github_release(
                tag_name="sash/0.6.5-rc__x",
                release_body="# notes",
                artefact_paths=[],
            )
