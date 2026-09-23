# Requirements Document

## Introduction

nf-ica-cli is a Python-based CLI toolkit for orchestrating Nextflow pipeline deployments to Illumina Connected Analytics (ICA). It operates on a separate configuration repository (nf-ica) containing YAML configs and patch files. The CLI manages patch registration, workflow version registration, annotated git tag creation for CI/CD handoff, release status transitions, and GitHub Actions-driven deployment to ICA projects filtered by context.

## Glossary

- **CLI**: The `nf-ica` command-line interface application built in Python
- **Config_Repo**: The nf-ica repository containing YAML configuration files and patch files
- **Workflow**: A Nextflow pipeline defined by a name and a remote git repository URI
- **Workflow_Version**: A specific tagged release of a Workflow, identified by a version tag and git commit ID
- **Context**: A deployment environment label (e.g., "development", "production") that controls which ICA projects receive a pipeline
- **ICA**: Illumina Connected Analytics platform where Nextflow pipelines are deployed and executed
- **ICA_Project**: A project within an ICA tenant, associated with one or more Contexts
- **Tenant**: An ICA organisational unit containing one or more ICA_Projects
- **Pipeline**: A deployed instance of a Workflow_Version on ICA, tracked in ica_pipelines.yaml
- **Release_Status**: The lifecycle state of a Pipeline, either DRAFT or RELEASED
- **Annotated_Tag**: A git tag in the format `<workflow-name>/<workflow-version-tag>__YYYYMMDDHHMMSS` whose message encodes deployment metadata (git commit ID, patch names, release status, and workflow version description)
- **Patch_File**: A standard unified diff file stored in the patches/ directory as `patches/<md5sum>.txt`, registered in Patches_Yaml, and referenced by patch name during deployment
- **Patches_Yaml**: The file `config/patches.yaml` in the Config_Repo that registers all patches with name, path, md5sum, and description
- **OIDC_Authentication**: OpenID Connect token exchange used in GitHub Actions to obtain a JWT for ICA API access
- **Workflows_Yaml**: The file `config/workflows.yaml` in the Config_Repo that registers workflow definitions and their versions
- **ICA_Pipelines_Yaml**: The file `config/ica_pipelines.yaml` in the Config_Repo that tracks deployed pipelines and their status
- **ICA_Config_Yaml**: The file `config/ica_config.yaml` in the Config_Repo that defines tenants, projects, and authentication
- **Contexts_Yaml**: The file `config/contexts.yaml` in the Config_Repo that defines available deployment contexts
- **GitHub_Release**: A GitHub Release page created for the annotated tag, containing deployment documentation and the pipeline source zip as a release artefact
- **SnakeMD**: A Python library for programmatically generating Markdown documents, used to construct the GitHub Release body

## Requirements

### Requirement 1: CLI Entry Point and Configuration Loading

**User Story:** As a developer, I want a single CLI entry point that loads configuration from the nf-ica repo, so that I can orchestrate pipeline operations with consistent settings.

#### Acceptance Criteria

1. THE CLI SHALL expose the command name `nf-ica` with subcommands `add-workflow-version`, `deploy-workflow-version`, `update-workflow-version-release-status`, `gh-actions-deploy-workflow`, and `register-patch`
2. WHEN invoked, THE CLI SHALL locate the Config_Repo by searching the current working directory and its parent directories up to the filesystem root for a directory containing `config/workflows.yaml`
3. WHEN the Config_Repo is not found after traversing to the filesystem root, THE CLI SHALL exit with a non-zero return code and an error message stating that no Config_Repo was found and listing the expected directory structure (`config/workflows.yaml`, `config/contexts.yaml`, `config/ica_config.yaml`, `config/ica_pipelines.yaml`, `config/patches.yaml`, `patches/`)
4. WHEN the Config_Repo is found, THE CLI SHALL parse Workflows_Yaml, Contexts_Yaml, ICA_Config_Yaml, ICA_Pipelines_Yaml, and Patches_Yaml; IF any file contains invalid YAML syntax, THEN THE CLI SHALL exit with a non-zero return code and an error message identifying the file and the parse error location
5. WHEN all configuration files parse successfully, THE CLI SHALL validate their contents according to Requirement 6 before executing any subcommand
6. WHEN Patches_Yaml does not exist in the Config_Repo, THE CLI SHALL treat it as an empty patch registry (zero registered patches) and continue execution

### Requirement 2: Add Workflow Version

**User Story:** As a pipeline developer, I want to register a new workflow version in workflows.yaml, so that the version is tracked and available for deployment.

#### Acceptance Criteria

1. WHEN the `add-workflow-version` subcommand is invoked with `--workflow-name`, `--workflow-repo-uri`, `--workflow-version-tag`, `--workflow-version-git-commit-id`, one or more `--workflow-version-context`, and `--workflow-ica-nextflow-version` flags, THE CLI SHALL add a version entry under the matching workflow in Workflows_Yaml containing the fields `tag`, `git_commit_id`, `contexts` (list), and `ica_nextflow_version`
2. WHEN the specified `--workflow-name` does not exist in Workflows_Yaml, THE CLI SHALL create a new workflow entry with `name` set to `--workflow-name` and `repo_uri` set to `--workflow-repo-uri`, and add the version entry underneath it
3. WHEN the specified `--workflow-name` exists but has a different `repo_uri` than the provided `--workflow-repo-uri`, THE CLI SHALL exit with a non-zero return code and an error message stating the URI mismatch including both the existing and provided URIs
4. WHEN the specified `--workflow-version-tag` already exists for the given workflow, THE CLI SHALL exit with a non-zero return code and an error message stating the version already exists
5. WHEN a `--workflow-version-context` value does not exist in Contexts_Yaml, THE CLI SHALL exit with a non-zero return code and an error message listing the invalid context value and the available contexts
6. WHEN any required flag (`--workflow-name`, `--workflow-repo-uri`, `--workflow-version-tag`, `--workflow-version-git-commit-id`, `--workflow-version-context`) is missing, THE CLI SHALL exit with a non-zero return code and an error message identifying the missing flag
7. THE CLI SHALL validate that `--workflow-version-git-commit-id` is a valid abbreviated or full hexadecimal git commit hash (7-40 characters, characters a-f and 0-9 only); IF validation fails, THEN THE CLI SHALL exit immediately with a non-zero return code and an error message before performing any write operations
8. THE CLI SHALL write the updated Workflows_Yaml preserving existing YAML formatting and comments

### Requirement 3: Deploy Workflow Version (Annotated Tag Creation)

**User Story:** As a pipeline developer, I want to create an annotated git tag encoding deployment metadata, so that GitHub Actions can use the tag to trigger pipeline deployment to ICA.

#### Acceptance Criteria

1. WHEN the `deploy-workflow-version` subcommand is invoked with `--workflow-name`, `--workflow-version-tag`, `--workflow-version-git-commit-id`, one or more `--workflow-version-context`, zero or more `--workflow-patch-name`, `--release-status`, and an optional `--workflow-version-description` flags, THE CLI SHALL create an annotated git tag named `<workflow-name>/<workflow-version-tag>__YYYYMMDDHHMMSS` using the current UTC timestamp formatted to second precision
2. THE CLI SHALL encode the git commit ID, list of patch names, list of contexts, release status, and workflow version description in the annotated tag message using the YAML schema defined in Requirement 7 (keys: `git_commit_id`, `contexts`, `patch_names`, `release_status`, `workflow_version_description`)
3. THE CLI SHALL validate all inputs (patch names, release status, workflow version registration, and context values) before creating the annotated tag; IF any validation fails, THEN THE CLI SHALL exit with a non-zero return code without creating the tag
4. WHEN a `--workflow-patch-name` value does not match a registered patch name in Patches_Yaml, THE CLI SHALL exit with a non-zero return code and an error message identifying the unregistered patch name
5. WHEN `--release-status` is not one of DRAFT or RELEASED, THE CLI SHALL exit with a non-zero return code and an error message listing valid release status values
6. WHEN the specified `--workflow-version-tag` is not registered in Workflows_Yaml for the given `--workflow-name`, THE CLI SHALL exit with a non-zero return code and an error message indicating the version must be added first
7. WHEN a `--workflow-version-context` value does not exist in Contexts_Yaml, THE CLI SHALL exit with a non-zero return code and an error message identifying the invalid context
8. IF an annotated tag with the generated name already exists in the repository, THEN THE CLI SHALL exit with a non-zero return code and an error message indicating the tag already exists

### Requirement 4: Update Workflow Version Release Status

**User Story:** As a pipeline developer, I want to transition a pipeline from DRAFT to RELEASED status, so that the pipeline is marked as production-ready in the tracking configuration.

#### Acceptance Criteria

1. WHEN the `update-workflow-version-release-status` subcommand is invoked with `--workflow-name`, `--workflow-version-tag`, and `--release-status` flags, THE CLI SHALL update the `release_status` field for the matching entry in ICA_Pipelines_Yaml
2. WHEN no matching entry exists in ICA_Pipelines_Yaml for the given workflow name and version tag, THE CLI SHALL exit with a non-zero return code and an error message indicating the pipeline entry was not found
3. WHEN `--release-status` is not one of DRAFT or RELEASED, THE CLI SHALL exit with a non-zero return code and an error message listing valid release status values
4. WHEN the current release status of the pipeline entry is RELEASED and `--release-status` is DRAFT, THE CLI SHALL exit with a non-zero return code and an error message indicating that status cannot be reverted from RELEASED to DRAFT
5. WHEN the current release status of the pipeline entry already matches `--release-status`, THE CLI SHALL exit with a zero return code without modifying ICA_Pipelines_Yaml
6. WHEN `--release-status` is RELEASED and the pipeline entry has associated patch names, THE CLI SHALL verify each referenced patch name exists in Patches_Yaml and the corresponding Patch_File exists at the path specified in Patches_Yaml; IF any patch name is not registered or its file is missing, THEN THE CLI SHALL exit with a non-zero return code and an error message identifying the missing patch
7. THE CLI SHALL write the updated ICA_Pipelines_Yaml preserving existing YAML formatting and comments

### Requirement 5: GitHub Actions Deploy Workflow

**User Story:** As a CI/CD pipeline, I want to deploy a workflow version to ICA projects matching the workflow's contexts, so that pipelines are automatically provisioned in the correct environments.

#### Acceptance Criteria

1. WHEN the `gh-actions-deploy-workflow` subcommand is invoked with `--workflow-name`, `--workflow-version`, and `--annotated-tag-name` flags, THE CLI SHALL parse the annotated tag message to extract deployment metadata (git commit ID, patch names, contexts, release status, and workflow version description)
2. THE CLI SHALL identify target ICA_Projects by selecting every ICA_Project whose context attributes in ICA_Config_Yaml share at least one context value in common with the workflow version's contexts extracted from the annotated tag message
3. WHEN no ICA_Projects match the workflow version's contexts, THE CLI SHALL exit with a non-zero return code and an error message indicating no deployment targets were found
4. THE CLI SHALL authenticate to each target ICA_Project using OIDC_Authentication by assuming the configured AWS role ARN and retrieving the ICA JWT from the configured secret ARN
5. IF OIDC_Authentication fails for an ICA_Project, THEN THE CLI SHALL log the failure, skip that project, and continue deploying to remaining projects
6. THE CLI SHALL clone the workflow source repository identified by `repo_uri` in Workflows_Yaml for the given `--workflow-name` at the git commit ID extracted from the annotated tag message into a temporary directory, and remove the temporary directory after deployment completes or fails
7. THE CLI SHALL resolve each patch name from the annotated tag message to its file path using Patches_Yaml and apply each Patch_File to the cloned source in the order specified in the annotated tag message
8. IF a Patch_File fails to apply cleanly, THEN THE CLI SHALL exit with a non-zero return code and an error message identifying the failing patch name and the conflict details
9. THE CLI SHALL always create a new pipeline on ICA using the ICA API with the patched source, specifying the Nextflow version from ICA_Config_Yaml `default_nextflow_version`; iterative development on draft pipelines is performed directly via the `icav2` CLI outside of this tool
10. WHEN deployment to an ICA_Project succeeds, THE CLI SHALL record the pipeline ID in ICA_Pipelines_Yaml with the workflow name, version, git commit ID, tenant, contexts, patch names, release status, and ICA Nextflow version
11. THE CLI SHALL write the updated ICA_Pipelines_Yaml preserving existing YAML formatting and comments
12. IF one or more ICA_Projects were skipped due to OIDC_Authentication failure and at least one deployment succeeded, THEN THE CLI SHALL exit with a non-zero return code and a summary message listing the skipped projects alongside the successfully deployed projects
13. WHEN at least one deployment succeeds, THE CLI SHALL create a zip archive of the patched Nextflow pipeline source and attach it as a release artefact to the GitHub Release associated with the annotated tag
14. WHEN at least one deployment succeeds, THE CLI SHALL generate a GitHub Release page body using snakemd containing: workflow name, workflow version, git commit ID, workflow version description, a table of deployed pipeline IDs and their target ICA project names/contexts, a list of applied patches (if any), the release status, and the Nextflow version used
15. WHEN all deployments are skipped due to authentication failures (zero successes), THE CLI SHALL NOT create a GitHub Release

### Requirement 6: YAML Configuration Validation

**User Story:** As a developer, I want the CLI to validate configuration files on load, so that malformed or inconsistent configs are caught early with clear error messages.

#### Acceptance Criteria

1. WHEN Workflows_Yaml is loaded, THE CLI SHALL validate that each workflow entry contains a non-empty `name` and `repo_uri`, and each version entry contains a non-empty `tag`, `git_commit_id`, at least one `contexts` value, and that every `contexts` value references a context name defined in Contexts_Yaml
2. WHEN Contexts_Yaml is loaded, THE CLI SHALL validate that each context entry contains a non-empty `name` and that no two context entries share the same `name`
3. WHEN ICA_Config_Yaml is loaded, THE CLI SHALL validate that each tenant contains a non-empty `name` and `id`, each project contains a non-empty `id`, `name`, and at least one `contexts` value, and that every project `contexts` value references a context name defined in Contexts_Yaml
4. WHEN ICA_Pipelines_Yaml is loaded and contains entries, THE CLI SHALL validate that each pipeline entry contains `workflow_name`, `workflow_version`, `git_commit_id`, `release_status` (one of DRAFT or RELEASED), at least one `tenants` value, and at least one `contexts` value
5. WHEN Patches_Yaml is loaded, THE CLI SHALL validate that each patch entry contains a non-empty `name`, `path`, `md5sum`, and `description`, that no two patch entries share the same `name`, and that the file at the referenced `path` exists in the Config_Repo
6. WHEN a validation error is detected, THE CLI SHALL exit with a non-zero return code and an error message identifying the file, the field, and the nature of the violation

### Requirement 7: Annotated Tag Message Format

**User Story:** As a developer, I want a well-defined tag message format, so that GitHub Actions can reliably parse deployment metadata from annotated tags.

#### Acceptance Criteria

1. THE CLI SHALL serialize the annotated tag message as a YAML document containing exactly the keys: `git_commit_id` (string, non-empty), `contexts` (list of one or more strings), `patch_names` (list of zero or more strings), `release_status` (string, one of DRAFT or RELEASED), and `workflow_version_description` (string, may be empty)
2. WHEN the `gh-actions-deploy-workflow` subcommand parses an annotated tag message, THE CLI SHALL deserialize the YAML document and validate that all five keys defined in criterion 1 are present with the correct types
3. IF an annotated tag message is missing a required key, contains an unknown key, or contains a value that does not match the expected type, THEN THE CLI SHALL exit with a non-zero return code and an error message identifying the key and the nature of the violation
4. THE CLI SHALL guarantee that serializing valid tag metadata and then parsing the resulting YAML document produces a metadata object with identical field values for all five keys
5. WHEN the `deploy-workflow-version` subcommand is invoked with no `--workflow-patch-name` flags, THE CLI SHALL serialize the `patch_names` key as an empty list in the annotated tag message

### Requirement 8: Register Patch

**User Story:** As a pipeline developer, I want to register a patch file with a name and description, so that patches are stored by content hash, deduplicated, and reusable across pipelines.

#### Acceptance Criteria

1. WHEN the `register-patch` subcommand is invoked with `--file`, `--name`, and `--description` flags, THE CLI SHALL compute the MD5 checksum of the entire file contents specified by `--file`
2. WHEN the computed MD5 checksum does not match any existing entry's `md5sum` in Patches_Yaml, THE CLI SHALL copy the file to `patches/<md5sum>.txt` in the Config_Repo
3. WHEN the computed MD5 checksum matches an existing entry's `md5sum` in Patches_Yaml, THE CLI SHALL skip copying the file and reuse the existing patch file path
4. THE CLI SHALL add an entry to Patches_Yaml with the patch `name`, `path` (as `patches/<md5sum>.txt`), `md5sum`, and `description`
5. THE CLI SHALL check for name collisions in Patches_Yaml before performing any file copy operations; WHEN a patch with the same `name` already exists in Patches_Yaml, THE CLI SHALL exit immediately with a non-zero return code and an error message indicating the patch name is already registered
6. WHEN the file specified by `--file` does not exist or is not readable, THE CLI SHALL exit with a non-zero return code and an error message identifying the file path and the access error
7. THE CLI SHALL validate that `--name` contains only alphanumeric characters, hyphens, and underscores
8. THE CLI SHALL write the updated Patches_Yaml preserving existing YAML formatting and comments
