"""Unit tests for nf_ica_cli.config_validation module."""

import pytest
from pathlib import Path

from nf_ica_cli.config import (
    AppConfig,
    Context,
    IcaConfig,
    IcaProject,
    OidcAuth,
    PipelineEntry,
    Tenant,
    Workflow,
    WorkflowVersion,
)
from nf_ica_cli.config_validation import validate_config
from nf_ica_cli.patches import PatchEntry


def _make_config(
    tmp_path,
    workflows=None,
    contexts=None,
    ica_config=None,
    pipelines=None,
    patches=None,
):
    """Helper to build an AppConfig with sensible defaults."""
    if contexts is None:
        contexts = [
            Context(name="development", description="Dev env"),
            Context(name="production", description="Prod env"),
        ]
    if workflows is None:
        workflows = []
    if ica_config is None:
        ica_config = IcaConfig(tenants=[], default_nextflow_version="25.10")
    if pipelines is None:
        pipelines = []
    if patches is None:
        patches = []

    return AppConfig(
        config_repo=tmp_path,
        workflows=workflows,
        contexts=contexts,
        ica_config=ica_config,
        pipelines=pipelines,
        patches=patches,
    )


class TestValidateContexts:
    """Tests for contexts.yaml validation (Requirement 6.2)."""

    def test_valid_contexts_pass(self, tmp_path):
        """Valid contexts pass validation without error."""
        config = _make_config(tmp_path)
        validate_config(config)  # Should not raise

    def test_empty_context_name_raises(self, tmp_path):
        """Empty context name raises SystemExit."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="", description="Empty name")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "VALIDATION" in msg
        assert "contexts.yaml" in msg
        assert "name" in msg
        assert "must not be empty" in msg

    def test_whitespace_only_context_name_raises(self, tmp_path):
        """Whitespace-only context name raises SystemExit."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="   ", description="Spaces only")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "must not be empty" in msg

    def test_duplicate_context_name_raises(self, tmp_path):
        """Duplicate context names raise SystemExit."""
        config = _make_config(
            tmp_path,
            contexts=[
                Context(name="dev", description="First"),
                Context(name="dev", description="Second"),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "VALIDATION" in msg
        assert "Duplicate context name" in msg
        assert "'dev'" in msg


class TestValidateWorkflows:
    """Tests for workflows.yaml validation (Requirement 6.1)."""

    def test_valid_workflow_passes(self, tmp_path):
        """A workflow with valid fields passes validation."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(
                    name="test-wf",
                    repo_uri="https://github.com/org/repo",
                    versions=[
                        WorkflowVersion(
                            tag="1.0.0",
                            git_commit_id="abc1234",
                            contexts=["development"],
                        )
                    ],
                )
            ],
        )
        validate_config(config)  # Should not raise

    def test_empty_workflow_name_raises(self, tmp_path):
        """Empty workflow name raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(name="", repo_uri="https://example.com", versions=[])
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "VALIDATION" in msg
        assert "workflows.yaml" in msg
        assert "name" in msg
        assert "must not be empty" in msg

    def test_empty_repo_uri_raises(self, tmp_path):
        """Empty repo_uri raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(name="my-wf", repo_uri="", versions=[])
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "repo_uri" in msg
        assert "must not be empty" in msg

    def test_empty_version_tag_raises(self, tmp_path):
        """Empty version tag raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(
                    name="my-wf",
                    repo_uri="https://example.com",
                    versions=[
                        WorkflowVersion(
                            tag="",
                            git_commit_id="abc1234",
                            contexts=["development"],
                        )
                    ],
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "tag" in msg
        assert "must not be empty" in msg

    def test_empty_git_commit_id_raises(self, tmp_path):
        """Empty git_commit_id raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(
                    name="my-wf",
                    repo_uri="https://example.com",
                    versions=[
                        WorkflowVersion(
                            tag="1.0.0",
                            git_commit_id="",
                            contexts=["development"],
                        )
                    ],
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "git_commit_id" in msg
        assert "must not be empty" in msg

    def test_empty_contexts_list_raises(self, tmp_path):
        """Version with no contexts raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(
                    name="my-wf",
                    repo_uri="https://example.com",
                    versions=[
                        WorkflowVersion(
                            tag="1.0.0",
                            git_commit_id="abc1234",
                            contexts=[],
                        )
                    ],
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "at least one context" in msg

    def test_invalid_context_reference_raises(self, tmp_path):
        """Context value not in contexts.yaml raises SystemExit."""
        config = _make_config(
            tmp_path,
            workflows=[
                Workflow(
                    name="my-wf",
                    repo_uri="https://example.com",
                    versions=[
                        WorkflowVersion(
                            tag="1.0.0",
                            git_commit_id="abc1234",
                            contexts=["nonexistent"],
                        )
                    ],
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "undefined context" in msg
        assert "'nonexistent'" in msg
        assert "Available contexts" in msg


class TestValidateIcaConfig:
    """Tests for ica_config.yaml validation (Requirement 6.3)."""

    def test_valid_ica_config_passes(self, tmp_path):
        """Valid ICA config passes validation."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[
                    Tenant(
                        name="my-tenant",
                        id="tenant-id-123",
                        projects=[
                            IcaProject(
                                id="proj-id-1",
                                name="my-project",
                                oidc_auth=[],
                                contexts=["development"],
                            )
                        ],
                    )
                ],
                default_nextflow_version="25.10",
            ),
        )
        validate_config(config)  # Should not raise

    def test_empty_tenant_name_raises(self, tmp_path):
        """Empty tenant name raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[Tenant(name="", id="some-id", projects=[])],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "VALIDATION" in msg
        assert "ica_config.yaml" in msg
        assert "name" in msg
        assert "must not be empty" in msg

    def test_empty_tenant_id_raises(self, tmp_path):
        """Empty tenant id raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[Tenant(name="my-tenant", id="", projects=[])],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "id" in msg
        assert "must not be empty" in msg

    def test_empty_project_id_raises(self, tmp_path):
        """Empty project id raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[
                    Tenant(
                        name="my-tenant",
                        id="tid",
                        projects=[
                            IcaProject(
                                id="",
                                name="proj",
                                oidc_auth=[],
                                contexts=["development"],
                            )
                        ],
                    )
                ],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "id" in msg
        assert "must not be empty" in msg

    def test_empty_project_name_raises(self, tmp_path):
        """Empty project name raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[
                    Tenant(
                        name="my-tenant",
                        id="tid",
                        projects=[
                            IcaProject(
                                id="pid",
                                name="",
                                oidc_auth=[],
                                contexts=["development"],
                            )
                        ],
                    )
                ],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "name" in msg
        assert "must not be empty" in msg

    def test_project_no_contexts_raises(self, tmp_path):
        """Project with no contexts raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[
                    Tenant(
                        name="my-tenant",
                        id="tid",
                        projects=[
                            IcaProject(
                                id="pid",
                                name="proj",
                                oidc_auth=[],
                                contexts=[],
                            )
                        ],
                    )
                ],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "at least one context" in msg

    def test_project_invalid_context_raises(self, tmp_path):
        """Project referencing undefined context raises SystemExit."""
        config = _make_config(
            tmp_path,
            ica_config=IcaConfig(
                tenants=[
                    Tenant(
                        name="my-tenant",
                        id="tid",
                        projects=[
                            IcaProject(
                                id="pid",
                                name="proj",
                                oidc_auth=[],
                                contexts=["staging"],
                            )
                        ],
                    )
                ],
                default_nextflow_version="25.10",
            ),
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "undefined context" in msg
        assert "'staging'" in msg
        assert "Available contexts" in msg


class TestValidatePipelines:
    """Tests for ica_pipelines.yaml validation (Requirement 6.4)."""

    def _valid_pipeline(self):
        return PipelineEntry(
            workflow_name="my-wf",
            workflow_version="1.0.0",
            git_commit_id="abc1234",
            pipeline_id="pipe-123",
            release_status="DRAFT",
            tenants=["tenant-a"],
            contexts=["development"],
            patch_files=[],
            ica_nextflow_version="25.10",
        )

    def test_valid_pipeline_passes(self, tmp_path):
        """A valid pipeline entry passes validation."""
        config = _make_config(tmp_path, pipelines=[self._valid_pipeline()])
        validate_config(config)  # Should not raise

    def test_empty_workflow_name_raises(self, tmp_path):
        """Pipeline with empty workflow_name raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.workflow_name = ""
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "workflow_name" in msg
        assert "must not be empty" in msg

    def test_empty_workflow_version_raises(self, tmp_path):
        """Pipeline with empty workflow_version raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.workflow_version = ""
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "workflow_version" in msg
        assert "must not be empty" in msg

    def test_empty_git_commit_id_raises(self, tmp_path):
        """Pipeline with empty git_commit_id raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.git_commit_id = ""
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "git_commit_id" in msg
        assert "must not be empty" in msg

    def test_invalid_release_status_raises(self, tmp_path):
        """Pipeline with invalid release_status raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.release_status = "INVALID"
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "release_status" in msg
        assert "'INVALID'" in msg
        assert "DRAFT" in msg
        assert "RELEASED" in msg

    def test_empty_tenants_raises(self, tmp_path):
        """Pipeline with no tenants raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.tenants = []
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "tenants" in msg
        assert "at least one tenant" in msg

    def test_empty_contexts_raises(self, tmp_path):
        """Pipeline with no contexts raises SystemExit."""
        pipeline = self._valid_pipeline()
        pipeline.contexts = []
        config = _make_config(tmp_path, pipelines=[pipeline])

        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "contexts" in msg
        assert "at least one context" in msg

    def test_released_status_passes(self, tmp_path):
        """Pipeline with RELEASED status passes validation."""
        pipeline = self._valid_pipeline()
        pipeline.release_status = "RELEASED"
        config = _make_config(tmp_path, pipelines=[pipeline])
        validate_config(config)  # Should not raise


class TestValidatePatches:
    """Tests for patches.yaml validation (Requirement 6.5)."""

    def test_valid_patch_passes(self, tmp_path):
        """A valid patch entry with existing file passes."""
        # Create the patch file
        patches_dir = tmp_path / "patches"
        patches_dir.mkdir()
        (patches_dir / "abc123.txt").write_text("patch content")

        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="fix-memory",
                    path="patches/abc123.txt",
                    md5sum="abc123",
                    description="Fix memory issue",
                )
            ],
        )
        validate_config(config)  # Should not raise

    def test_empty_patch_name_raises(self, tmp_path):
        """Patch with empty name raises SystemExit."""
        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="",
                    path="patches/abc123.txt",
                    md5sum="abc123",
                    description="A patch",
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "patches.yaml" in msg
        assert "name" in msg
        assert "must not be empty" in msg

    def test_empty_patch_path_raises(self, tmp_path):
        """Patch with empty path raises SystemExit."""
        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="my-patch",
                    path="",
                    md5sum="abc123",
                    description="A patch",
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "path" in msg
        assert "must not be empty" in msg

    def test_empty_patch_md5sum_raises(self, tmp_path):
        """Patch with empty md5sum raises SystemExit."""
        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="my-patch",
                    path="patches/abc.txt",
                    md5sum="",
                    description="A patch",
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "md5sum" in msg
        assert "must not be empty" in msg

    def test_empty_patch_description_raises(self, tmp_path):
        """Patch with empty description raises SystemExit."""
        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="my-patch",
                    path="patches/abc.txt",
                    md5sum="abc123",
                    description="",
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "description" in msg
        assert "must not be empty" in msg

    def test_duplicate_patch_names_raises(self, tmp_path):
        """Duplicate patch names raise SystemExit."""
        patches_dir = tmp_path / "patches"
        patches_dir.mkdir()
        (patches_dir / "abc.txt").write_text("content1")
        (patches_dir / "def.txt").write_text("content2")

        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="my-patch",
                    path="patches/abc.txt",
                    md5sum="abc",
                    description="First",
                ),
                PatchEntry(
                    name="my-patch",
                    path="patches/def.txt",
                    md5sum="def",
                    description="Second",
                ),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "Duplicate patch name" in msg
        assert "'my-patch'" in msg

    def test_missing_patch_file_raises(self, tmp_path):
        """Patch with non-existent file raises SystemExit."""
        config = _make_config(
            tmp_path,
            patches=[
                PatchEntry(
                    name="my-patch",
                    path="patches/nonexistent.txt",
                    md5sum="abc123",
                    description="A patch",
                )
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "file not found" in msg
        assert "nonexistent.txt" in msg


class TestValidateConfigErrorFormat:
    """Tests for error message format (Requirement 6.6)."""

    def test_error_identifies_file(self, tmp_path):
        """Error message includes the file name."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="", description="Bad")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "file=contexts.yaml" in msg

    def test_error_identifies_field(self, tmp_path):
        """Error message includes the field path."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="", description="Bad")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "field=contexts[0].name" in msg

    def test_error_identifies_violation(self, tmp_path):
        """Error message describes the violation."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="", description="Bad")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert "must not be empty" in msg

    def test_error_starts_with_standard_prefix(self, tmp_path):
        """All validation errors start with 'Error: [VALIDATION]'."""
        config = _make_config(
            tmp_path,
            contexts=[Context(name="", description="Bad")],
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_config(config)

        msg = str(exc_info.value)
        assert msg.startswith("Error: [VALIDATION]")
