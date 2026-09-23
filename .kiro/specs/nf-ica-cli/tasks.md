# Implementation Plan: nf-ica-cli

## Overview

Implement a Python CLI toolkit (`nf-ica`) for orchestrating Nextflow pipeline deployments to Illumina Connected Analytics (ICA). The implementation follows a bottom-up approach: core utilities first (YAML I/O, validators, tag codec, patch manager, git operations, ICA client), then configuration loading, and finally the CLI entry point wiring everything together.

## Tasks

- [x] 1. Set up project structure and core utilities
  - [x] 1.1 Create Python package structure and pyproject.toml
    - Create `nf_ica_cli/` package directory with `__init__.py`
    - Create `pyproject.toml` with dependencies: docopt, ruamel.yaml, wrapica, boto3, snakemd
    - Create `tests/` directory structure: `tests/unit/`, `tests/property/`, `tests/integration/`
    - Add dev dependencies: pytest, hypothesis, pytest-mock
    - Create entry point `nf-ica = nf_ica_cli.cli:main`
    - _Requirements: 1.1_

  - [x] 1.2 Implement YAML I/O module (`nf_ica_cli/yaml_io.py`)
    - Implement `load_yaml(path: Path) -> dict` using ruamel.yaml with `preserve_quotes = True`
    - Implement `save_yaml(path: Path, data: dict) -> None` using ruamel.yaml with comment preservation
    - Handle file-not-found and YAML parse errors with clear error messages including file path and line/column
    - _Requirements: 2.8, 4.7, 5.11, 8.8_

  - [x] 1.3 Write property test for YAML comment preservation
    - **Property 2: YAML comment and formatting preservation**
    - **Validates: Requirements 2.8, 4.7, 5.11, 8.8**

  - [x] 1.4 Implement validators module (`nf_ica_cli/validators.py`)
    - Implement `validate_git_commit_id(value: str) -> bool` — accepts 7-40 hex chars [a-f0-9]
    - Implement `validate_patch_name(value: str) -> bool` — accepts non-empty [a-zA-Z0-9_-]
    - Implement `validate_release_status(value: str) -> bool` — accepts only "DRAFT" or "RELEASED"
    - Implement `validate_context(value: str, defined_contexts: List[str]) -> bool` — checks membership
    - Each validator raises a descriptive ValueError on failure
    - _Requirements: 2.7, 3.5, 4.3, 8.7, 2.5, 3.7_

  - [x] 1.5 Write property tests for validators
    - **Property 4: Git commit ID validation**
    - **Property 5: Patch name format validation**
    - **Property 6: Release status validation**
    - **Property 7: Context cross-reference validation**
    - **Validates: Requirements 2.7, 8.7, 3.5, 4.3, 2.5, 3.7**

- [x] 2. Implement tag codec and patch manager
  - [x] 2.1 Implement tag codec (`nf_ica_cli/tag_codec.py`)
    - Define `TagMetadata` dataclass with fields: `git_commit_id`, `contexts`, `patch_names`, `release_status`, `workflow_version_description`
    - Implement `encode_tag_message(metadata: TagMetadata) -> str` — serialize to YAML with exactly 5 keys
    - Implement `decode_tag_message(message: str) -> TagMetadata` — deserialize YAML, validate all 5 keys present with correct types
    - Implement `make_tag_name(workflow_name: str, version_tag: str) -> str` — format `<name>/<tag>__YYYYMMDDHHMMSS`
    - Raise clear errors for missing keys, unknown keys, or type mismatches
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 3.1_

  - [x] 2.2 Write property tests for tag codec
    - **Property 1: Tag codec round-trip**
    - **Property 13: Malformed tag message rejection**
    - **Validates: Requirements 7.4, 7.1, 7.2, 3.2, 7.3**

  - [x] 2.3 Implement patch manager (`nf_ica_cli/patches.py`)
    - Implement `compute_md5(file_path: Path) -> str` — MD5 hex digest of file contents
    - Implement `register_patch(config_repo, source_file, name, description, existing_patches) -> PatchEntry` — compute MD5, copy to `patches/<md5sum>.txt` if new, check name collision first
    - Implement `apply_patches(repo_dir, patch_names, patches_registry, config_repo) -> None` — resolve paths, apply in order with `git apply`
    - Validate patch name format before any file operations
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 5.7, 5.8_

  - [x] 2.4 Write property test for patch storage determinism
    - **Property 3: Content-addressed patch storage determinism**
    - **Validates: Requirements 8.1, 8.2, 8.3**

- [x] 3. Implement git operations and ICA client
  - [x] 3.1 Implement git operations (`nf_ica_cli/git_ops.py`)
    - Implement `create_annotated_tag(repo_dir, tag_name, message) -> None` — run `git tag -a <name> -m <message>`
    - Implement `tag_exists(repo_dir, tag_name) -> bool` — check via `git tag -l <name>`
    - Implement `clone_at_commit(repo_uri, commit_id, target_dir) -> None` — shallow clone and checkout
    - Implement `get_tag_message(repo_dir, tag_name) -> str` — retrieve via `git tag -l --format='%(contents)' <name>`
    - Handle subprocess errors with clear error messages
    - _Requirements: 3.1, 3.8, 5.6_

  - [x] 3.2 Implement ICA client (`nf_ica_cli/ica_client.py`)
    - Implement `authenticate_oidc(aws_role_arn, secret_arn) -> str` — assume AWS role via OIDC, retrieve JWT from Secrets Manager, set wrapica session
    - Implement `create_pipeline(project_id, workflow_name, version, source_dir, nextflow_version, description) -> str` — zip source and create via wrapica
    - Define `DeploymentTarget` dataclass
    - _Requirements: 5.4, 5.9_

  - [x] 3.3 Implement release page generator (`nf_ica_cli/release_page.py`)
    - Define `DeploymentResult` dataclass with fields: `project_name`, `project_id`, `tenant_name`, `pipeline_id`, `contexts`
    - Implement `generate_release_body(...)` using snakemd to build markdown: workflow header, commit ID, description, release status, nextflow version, deployment table (project/tenant/pipeline ID/contexts), patches list, skipped projects
    - Implement `create_pipeline_zip(source_dir, output_path) -> Path` — zip the patched pipeline source directory
    - Implement `create_github_release(tag_name, release_body, artefact_paths) -> None` — call `gh release create` with notes and artefact attachments
    - _Requirements: 5.13, 5.14, 5.15_

- [x] 4. Checkpoint - Core modules complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement configuration loader and validator
  - [x] 5.1 Implement config dataclasses and loader (`nf_ica_cli/config.py`)
    - Define all dataclasses: `WorkflowVersion`, `Workflow`, `Context`, `OidcAuth`, `IcaProject`, `Tenant`, `IcaConfig`, `PipelineEntry`, `PatchEntry`, `AppConfig`
    - Implement `find_config_repo() -> Path` — traverse CWD upward looking for `config/workflows.yaml`
    - Implement `load_and_validate_config(config_repo: Path) -> AppConfig` — load all YAML files, parse into dataclasses
    - Handle missing Patches_Yaml as empty list (per Requirement 1.6)
    - _Requirements: 1.2, 1.3, 1.4, 1.6_

  - [x] 5.2 Write property test for config repo discovery
    - **Property 8: Config repo discovery**
    - **Validates: Requirements 1.2**

  - [x] 5.3 Implement configuration validation logic
    - Validate Workflows_Yaml: non-empty name/repo_uri, version fields, context cross-references
    - Validate Contexts_Yaml: non-empty names, uniqueness
    - Validate ICA_Config_Yaml: tenant/project fields, context cross-references
    - Validate ICA_Pipelines_Yaml: required fields, release_status enum
    - Validate Patches_Yaml: required fields, name uniqueness, file existence
    - Produce error messages identifying file, field, and violation
    - _Requirements: 1.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 5.4 Write property test for configuration validation
    - **Property 12: Configuration validation completeness**
    - **Validates: Requirements 1.5, 6.1, 6.2, 6.3, 6.4, 6.5**

- [x] 6. Implement subcommand handlers
  - [x] 6.1 Implement `register-patch` handler
    - Extract `--file`, `--name`, `--description` from docopt args
    - Validate patch name format and file accessibility
    - Check name collision in existing patches
    - Call `register_patch()` from patches module
    - Update Patches_Yaml via `save_yaml()`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 6.2 Implement `add-workflow-version` handler
    - Extract all required flags from docopt args
    - Validate git commit ID, context values
    - Check for URI mismatch if workflow exists
    - Check for duplicate version tag
    - Add version entry (or create new workflow) in workflows data
    - Write updated Workflows_Yaml preserving comments
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 6.3 Implement `deploy-workflow-version` handler
    - Extract all flags from docopt args
    - Validate release status, patch names against registry, context values, version registration
    - Generate tag name with UTC timestamp
    - Check tag doesn't already exist
    - Encode tag metadata via tag codec
    - Create annotated tag via git_ops
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 6.4 Implement `update-workflow-version-release-status` handler
    - Extract `--workflow-name`, `--workflow-version-tag`, `--release-status`
    - Find matching pipeline entry in ICA_Pipelines_Yaml
    - Validate release status value
    - Check RELEASED→DRAFT rejection
    - Check idempotent no-op case (same status)
    - When releasing: verify all referenced patches exist
    - Write updated ICA_Pipelines_Yaml preserving comments
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 6.5 Write property tests for status transitions
    - **Property 10: Release status transition irreversibility**
    - **Property 11: Status update idempotence**
    - **Validates: Requirements 4.4, 4.5**

  - [x] 6.6 Implement `gh-actions-deploy-workflow` handler
    - Extract `--workflow-name`, `--workflow-version`, `--annotated-tag-name`
    - Retrieve and decode annotated tag message via git_ops and tag codec
    - Identify target projects via context-based filtering on ICA_Config_Yaml
    - For each target project: authenticate OIDC, clone repo at commit, apply patches, create new pipeline
    - Record pipeline IDs in ICA_Pipelines_Yaml
    - After successful deployments: zip patched pipeline source, generate release body with snakemd (deployment table, patches, metadata), create GitHub Release with `gh` CLI attaching the zip artefact
    - Skip GitHub Release creation if all deployments failed
    - Handle partial deployment (some auth failures) with summary exit
    - Clean up temporary clone directory
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14, 5.15_

  - [x] 6.7 Write property test for context-based project filtering
    - **Property 9: Context-based project filtering**
    - **Validates: Requirements 5.2**

- [x] 7. Implement CLI entry point and wiring
  - [x] 7.1 Implement CLI entry point (`nf_ica_cli/cli.py`)
    - Define top-level docopt usage string with all subcommands
    - Implement `main()` function: parse args, find config repo, load/validate config, dispatch to handler
    - Wire all subcommand handlers from task 6
    - Handle top-level exceptions with formatted error messages and non-zero exit codes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 7.2 Write unit tests for CLI argument parsing
    - Test valid argument combinations for each subcommand
    - Test missing required flags produce usage errors
    - Test `--help` and `--version` options
    - _Requirements: 1.1, 2.6_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design document
- Unit tests validate specific examples and edge cases
- The project uses Python with docopt, ruamel.yaml, wrapica, snakemd, and subprocess as core dependencies
- Hypothesis is the PBT library for property-based tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.3", "1.5", "2.1", "2.3"] },
    { "id": 3, "tasks": ["2.2", "2.4", "3.1", "3.2", "3.3"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3"] },
    { "id": 6, "tasks": ["5.4", "6.1", "6.2", "6.3", "6.4"] },
    { "id": 7, "tasks": ["6.5", "6.6"] },
    { "id": 8, "tasks": ["6.7", "7.1"] },
    { "id": 9, "tasks": ["7.2"] }
  ]
}
```
