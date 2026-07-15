"""Property-based tests for configuration validation completeness.

Tests Property 12 from the design document using Hypothesis.
"""

import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

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


# --- Strategies ---

# Safe text for names/identifiers
safe_name_chars = "abcdefghijklmnopqrstuvwxyz0123456789"
safe_names = st.text(alphabet=safe_name_chars, min_size=1, max_size=20)

# Non-empty text (for description-like fields)
non_empty_text = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())

# Valid release statuses
valid_release_statuses = st.sampled_from(["DRAFT", "RELEASED"])

# Valid git commit IDs (7-40 hex chars)
valid_git_commit_ids = st.text(alphabet="abcdef0123456789", min_size=7, max_size=40)

# Valid patch names (alphanumeric, hyphens, underscores)
valid_patch_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=20,
)

# MD5 hex strings
md5_hex = st.text(alphabet="abcdef0123456789", min_size=32, max_size=32)


@st.composite
def valid_app_configs(draw: st.DrawFn) -> AppConfig:
    """Generate a fully valid AppConfig where all cross-references resolve."""
    # 1. Generate unique context names
    num_contexts = draw(st.integers(min_value=1, max_value=5))
    context_names = draw(
        st.lists(safe_names, min_size=num_contexts, max_size=num_contexts, unique=True)
    )
    contexts = [
        Context(name=name, description=f"Description for {name}")
        for name in context_names
    ]

    # 2. Generate workflows referencing valid contexts
    num_workflows = draw(st.integers(min_value=0, max_value=3))
    workflows = []
    for _ in range(num_workflows):
        wf_name = draw(safe_names)
        repo_uri = draw(st.from_regex(r"https://github\.com/[a-z]+/[a-z]+", fullmatch=True))
        num_versions = draw(st.integers(min_value=1, max_value=3))
        versions = []
        used_tags = set()
        for _ in range(num_versions):
            tag = draw(safe_names.filter(lambda t, ut=used_tags: t not in ut))
            used_tags.add(tag)
            git_commit_id = draw(valid_git_commit_ids)
            # Pick at least one valid context
            ver_contexts = draw(
                st.lists(
                    st.sampled_from(context_names),
                    min_size=1,
                    max_size=min(3, len(context_names)),
                )
            )
            versions.append(
                WorkflowVersion(
                    tag=tag,
                    git_commit_id=git_commit_id,
                    contexts=ver_contexts,
                )
            )
        workflows.append(Workflow(name=wf_name, repo_uri=repo_uri, versions=versions))

    # 3. Generate ICA config referencing valid contexts
    num_tenants = draw(st.integers(min_value=1, max_value=2))
    tenants = []
    for _ in range(num_tenants):
        tenant_name = draw(safe_names)
        tenant_id = draw(safe_names)
        num_projects = draw(st.integers(min_value=1, max_value=2))
        projects = []
        for _ in range(num_projects):
            proj_contexts = draw(
                st.lists(
                    st.sampled_from(context_names),
                    min_size=1,
                    max_size=min(3, len(context_names)),
                )
            )
            projects.append(
                IcaProject(
                    id=draw(safe_names),
                    name=draw(safe_names),
                    oidc_auth=[OidcAuth(aws_role_arn="arn:aws:iam::role", secret_arn="arn:aws:secretsmanager:secret")],
                    contexts=proj_contexts,
                )
            )
        tenants.append(Tenant(name=tenant_name, id=tenant_id, projects=projects))

    ica_config = IcaConfig(tenants=tenants, default_nextflow_version="23.10.0")

    # 4. Generate pipelines with valid statuses and non-empty required fields
    num_pipelines = draw(st.integers(min_value=0, max_value=3))
    pipelines = []
    for _ in range(num_pipelines):
        pipelines.append(
            PipelineEntry(
                workflow_name=draw(safe_names),
                workflow_version=draw(safe_names),
                git_commit_id=draw(valid_git_commit_ids),
                pipeline_id=draw(safe_names),
                release_status=draw(valid_release_statuses),
                tenants=[draw(safe_names)],
                contexts=[draw(st.sampled_from(context_names))],
                patch_files=[],
                ica_nextflow_version="23.10.0",
            )
        )

    # 5. Generate patches with unique names and actual files on disk
    num_patches = draw(st.integers(min_value=0, max_value=3))
    patch_names_list = draw(
        st.lists(valid_patch_names, min_size=num_patches, max_size=num_patches, unique=True)
    )

    # Create a temporary config repo with patch files
    config_repo = Path(tempfile.mkdtemp())
    patches_dir = config_repo / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)

    patches = []
    for pname in patch_names_list:
        md5 = draw(md5_hex)
        patch_path = f"patches/{md5}.txt"
        # Create the actual patch file
        (config_repo / patch_path).write_text(f"patch content for {pname}\n")
        patches.append(
            PatchEntry(name=pname, path=patch_path, md5sum=md5, description=f"Desc {pname}")
        )

    return AppConfig(
        config_repo=config_repo,
        workflows=workflows,
        contexts=contexts,
        ica_config=ica_config,
        pipelines=pipelines,
        patches=patches,
    )


@st.composite
def config_with_empty_required_field(draw: st.DrawFn) -> AppConfig:
    """Generate a config with at least one empty required field."""
    config = draw(valid_app_configs())

    # Choose which section to break
    section = draw(st.sampled_from(["workflow_name", "context_name", "tenant_name", "pipeline_wf_name", "patch_name"]))

    if section == "workflow_name" and config.workflows:
        config.workflows[0].name = ""
    elif section == "context_name":
        config.contexts[0].name = ""
    elif section == "tenant_name":
        config.ica_config.tenants[0].name = ""
    elif section == "pipeline_wf_name" and config.pipelines:
        config.pipelines[0].workflow_name = ""
    elif section == "patch_name" and config.patches:
        config.patches[0].name = ""
    else:
        # Fallback: always break a context name since we always have contexts
        config.contexts[0].name = ""

    return config


@st.composite
def config_with_duplicate_context_names(draw: st.DrawFn) -> AppConfig:
    """Generate a config with duplicate context names."""
    config = draw(valid_app_configs())
    assume(len(config.contexts) >= 1)

    # Duplicate the first context name by adding a copy
    dup_name = config.contexts[0].name
    config.contexts.append(Context(name=dup_name, description="Duplicate context"))

    return config


@st.composite
def config_with_duplicate_patch_names(draw: st.DrawFn) -> AppConfig:
    """Generate a config with duplicate patch names."""
    config = draw(valid_app_configs())

    # Add a patch with a duplicated name
    dup_name = draw(valid_patch_names)
    md5_1 = draw(md5_hex)
    md5_2 = draw(md5_hex)
    assume(md5_1 != md5_2)

    # Create patch files on disk
    patches_dir = config.config_repo / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    (config.config_repo / f"patches/{md5_1}.txt").write_text("content1\n")
    (config.config_repo / f"patches/{md5_2}.txt").write_text("content2\n")

    config.patches = [
        PatchEntry(name=dup_name, path=f"patches/{md5_1}.txt", md5sum=md5_1, description="Patch 1"),
        PatchEntry(name=dup_name, path=f"patches/{md5_2}.txt", md5sum=md5_2, description="Patch 2"),
    ]

    return config


@st.composite
def config_with_undefined_context_crossref(draw: st.DrawFn) -> AppConfig:
    """Generate a config where a workflow version references an undefined context."""
    config = draw(valid_app_configs())

    # Generate a context name that is NOT in defined contexts
    defined_names = {ctx.name for ctx in config.contexts}
    undefined_ctx = draw(safe_names.filter(lambda n: n not in defined_names))

    # Ensure we have a workflow with at least one version to break
    if not config.workflows:
        wf = Workflow(
            name="test_workflow",
            repo_uri="https://github.com/test/repo",
            versions=[
                WorkflowVersion(
                    tag="v1",
                    git_commit_id="abcdef1",
                    contexts=[undefined_ctx],
                )
            ],
        )
        config.workflows = [wf]
    else:
        # Inject undefined context into an existing workflow version
        config.workflows[0].versions[0].contexts = [undefined_ctx]

    return config


# --- Property 12: Configuration validation completeness ---
# Feature: nf-ica-cli, Property 12: For any configuration structure (workflows, contexts,
# ICA config, pipelines, patches), the validator SHALL accept it if and only if all required
# fields are present, all cross-references (contexts, patch names) resolve to existing
# definitions, and all uniqueness constraints (context names, patch names) are satisfied.


class TestConfigValidationCompleteness:
    """**Validates: Requirements 1.5, 6.1, 6.2, 6.3, 6.4, 6.5**"""

    @given(config=valid_app_configs())
    @settings(max_examples=100)
    def test_valid_config_passes_validation(self, config: AppConfig) -> None:
        """Any valid config with proper cross-references passes validation.

        A configuration with all required fields present, all context cross-references
        resolving to defined contexts, and all uniqueness constraints satisfied
        SHALL be accepted by the validator without raising SystemExit.
        """
        # Feature: nf-ica-cli, Property 12: Configuration validation completeness
        try:
            validate_config(config)
        finally:
            # Clean up temp directory
            shutil.rmtree(config.config_repo, ignore_errors=True)

    @given(config=config_with_empty_required_field())
    @settings(max_examples=100)
    def test_config_with_empty_required_fields_is_rejected(self, config: AppConfig) -> None:
        """Config with empty required fields is rejected.

        Any configuration where a required field is empty SHALL be rejected
        by the validator with a SystemExit.
        """
        # Feature: nf-ica-cli, Property 12: Configuration validation completeness
        try:
            with pytest.raises(SystemExit):
                validate_config(config)
        finally:
            shutil.rmtree(config.config_repo, ignore_errors=True)

    @given(config=config_with_duplicate_context_names())
    @settings(max_examples=100)
    def test_config_with_duplicate_context_names_is_rejected(self, config: AppConfig) -> None:
        """Config with duplicate context names is rejected.

        Any configuration where two or more contexts share the same name
        SHALL be rejected by the validator with a SystemExit.
        """
        # Feature: nf-ica-cli, Property 12: Configuration validation completeness
        try:
            with pytest.raises(SystemExit):
                validate_config(config)
        finally:
            shutil.rmtree(config.config_repo, ignore_errors=True)

    @given(config=config_with_duplicate_patch_names())
    @settings(max_examples=100)
    def test_config_with_duplicate_patch_names_is_rejected(self, config: AppConfig) -> None:
        """Config with duplicate patch names is rejected.

        Any configuration where two or more patches share the same name
        SHALL be rejected by the validator with a SystemExit.
        """
        # Feature: nf-ica-cli, Property 12: Configuration validation completeness
        try:
            with pytest.raises(SystemExit):
                validate_config(config)
        finally:
            shutil.rmtree(config.config_repo, ignore_errors=True)

    @given(config=config_with_undefined_context_crossref())
    @settings(max_examples=100)
    def test_config_with_undefined_context_crossrefs_is_rejected(self, config: AppConfig) -> None:
        """Config with undefined context cross-references is rejected.

        Any configuration where a workflow version, ICA project, or pipeline
        references a context name not defined in contexts.yaml SHALL be rejected
        by the validator with a SystemExit.
        """
        # Feature: nf-ica-cli, Property 12: Configuration validation completeness
        try:
            with pytest.raises(SystemExit):
                validate_config(config)
        finally:
            shutil.rmtree(config.config_repo, ignore_errors=True)
