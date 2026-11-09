# Requirements Document

## Introduction

The `collect-all-patches` subcommand enables users to reverse-engineer the set of patches applied to a Nextflow pipeline deployed on Illumina Connected Analytics (ICA). Given a source repository at a specific commit and a pipeline ID on ICA, the command downloads the pipeline source from ICA, compares it against the original repository source, and generates unified diff patches. These patches are output in the content-addressed format compatible with the existing nf-ica patch system (`patches/<md5>.txt`), enabling users to replicate the pipeline's customisations as a reproducible patch set.

## Glossary

- **CLI**: The `nf-ica` command-line interface tool defined in `nf_ica_cli`.
- **Pipeline_Source**: The collection of Nextflow source files (`.nf`, `.config`, etc.) that define a pipeline on ICA.
- **Source_Repository**: A Git repository containing the original Nextflow workflow source code.
- **ICA_Pipeline**: A Nextflow pipeline object deployed on Illumina Connected Analytics, identified by a project ID and pipeline ID.
- **Patch**: A unified diff file representing the difference between the Source_Repository file and the corresponding ICA_Pipeline file.
- **Patch_Registry**: The content-addressed storage system in the config repo where patches are stored as `patches/<md5>.txt` and referenced in `patches.yaml`.
- **Config_Repo**: The `nf-ica` configuration repository containing `workflows.yaml`, `patches.yaml`, and the `patches/` directory.
- **Collector**: The `collect-all-patches` subcommand handler module.
- **Pipeline_Exporter**: The component responsible for downloading Pipeline_Source files from an ICA_Pipeline.
- **Patch_Prompter**: The component responsible for interactively prompting the user for patch metadata (name, description) and handling duplicate detection during patch registration.

## Requirements

### Requirement 1: CLI Argument Parsing

**User Story:** As a pipeline developer, I want to invoke `nf-ica collect-all-patches` with parameters identifying the source repository and the ICA pipeline, so that the CLI can determine what to compare.

#### Acceptance Criteria

1. WHEN the user invokes `nf-ica collect-all-patches` with `--repo-uri=<value>`, `--commit-id=<value>`, `--project-id=<value>`, and `--pipeline-id=<value>` arguments, THE CLI SHALL parse all four arguments and make them available to the Collector handler as named string values.
2. IF any of `--repo-uri`, `--commit-id`, `--project-id`, or `--pipeline-id` is missing, THEN THE CLI SHALL print an error message to stderr identifying each missing argument by name and exit with status code 1.
3. WHEN the user invokes `nf-ica collect-all-patches --help`, THE CLI SHALL display usage text listing all four required arguments with their `--argument-name=<value>` syntax and a one-line description of each, then exit with status code 0.
4. IF the user provides an unrecognized argument to `nf-ica collect-all-patches`, THEN THE CLI SHALL print an error message to stderr indicating the unrecognized argument and exit with status code 1.
5. WHEN the user invokes `nf-ica collect-all-patches` with all four required arguments, THE CLI SHALL complete argument parsing within the docopt two-pass mechanism without importing heavy dependencies until parsing succeeds.

### Requirement 2: Source Repository Cloning

**User Story:** As a pipeline developer, I want the tool to clone the original source repository at the specified commit, so that I have a baseline to compare against.

#### Acceptance Criteria

1. WHEN the Collector receives a valid `--repo-uri` and `--commit-id`, THE Collector SHALL clone the Source_Repository into a uniquely-named temporary directory and checkout the specified commit within 300 seconds.
2. IF the clone operation fails due to an invalid or unreachable repository URI, THEN THE Collector SHALL display an error message containing the repository URI and exit with a non-zero status code.
3. IF the checkout operation fails due to an invalid commit ID, THEN THE Collector SHALL display an error message containing the commit ID and exit with a non-zero status code.
4. WHEN the Collector completes execution (successfully or on error), THE Collector SHALL attempt to remove the temporary clone directory; IF removal fails, THE Collector SHALL log a warning to stderr and continue with its exit procedure.
5. IF the clone operation exceeds 300 seconds, THEN THE Collector SHALL terminate the clone process, display an error message indicating a timeout, and exit with a non-zero status code.
6. IF the clone operation fails due to an authentication or permission error, THEN THE Collector SHALL display an error message indicating insufficient access to the repository and exit with a non-zero status code.

### Requirement 3: ICA Pipeline Source Export

**User Story:** As a pipeline developer, I want the tool to download the source files from my tinkered ICA pipeline, so that the tool can compare them against the original source.

#### Acceptance Criteria

1. WHEN the Collector receives a `--project-id` matching a UUID format and a `--pipeline-id` matching a UUID format, THE Pipeline_Exporter SHALL download all files stored in the ICA_Pipeline into a temporary directory, preserving the relative directory structure of the pipeline source.
2. IF the ICAV2_ACCESS_TOKEN environment variable is not set or is empty, THEN THE Pipeline_Exporter SHALL display an error message indicating the missing authentication token and exit with a non-zero status code without attempting any ICA API calls.
3. IF the ICA API call fails due to an expired or invalid authentication token, THEN THE Pipeline_Exporter SHALL halt execution immediately, display an error message indicating the authentication failure, and exit with a non-zero status code.
4. IF the ICA API call fails because the pipeline ID does not exist in the specified project, THEN THE Pipeline_Exporter SHALL display an error message containing the project ID and pipeline ID and exit with a non-zero status code.
5. IF the download of any pipeline source file fails after the download operation has started, THEN THE Pipeline_Exporter SHALL remove the temporary directory, display an error message indicating which file failed, and exit with a non-zero status code.
6. WHEN the Collector completes execution (successfully or on error), THE Collector SHALL attempt to remove the temporary pipeline export directory and all of its contents; IF removal fails, THE Collector SHALL log a warning to stderr and continue with its exit procedure.

### Requirement 4: Diff Generation

**User Story:** As a pipeline developer, I want the tool to generate unified diffs between the source repository and the ICA pipeline source, so that I can see exactly what was changed.

#### Acceptance Criteria

1. WHEN both the Source_Repository clone and the Pipeline_Source export are available as directories on disk, THE Collector SHALL generate a unified diff for each file that differs between the two directories, using file paths relative to the respective directory roots as the `a/` and `b/` prefixes.
2. WHEN a file exists in the Pipeline_Source but not in the Source_Repository, THE Collector SHALL generate a unified diff representing a new file addition using `git diff --no-index /dev/null <file>` format.
3. WHEN a file exists in the Source_Repository but not in the Pipeline_Source, THE Collector SHALL generate a unified diff representing a file deletion.
4. WHEN a file exists in both directories with identical content, THE Collector SHALL not generate a Patch for that file.
5. THE Collector SHALL use `git diff --no-index` to generate unified diffs compatible with `git apply`.
6. THE Collector SHALL exclude `.git/` directory contents from diff comparison.
7. IF `git diff --no-index` returns a non-zero exit code other than 1 (which indicates differences found) for any file comparison, THEN THE Collector SHALL raise an error identifying the file pair that failed.
8. THE Collector SHALL concatenate all per-file diffs into a single unified patch output, ordered alphabetically by file path relative to the directory root.

### Requirement 5: Interactive Patch Registration

**User Story:** As a pipeline developer, I want to interactively review and name each generated patch before registration, so that I can provide meaningful names and descriptions and skip patches I do not need.

#### Acceptance Criteria

1. WHEN the Collector generates one or more Patches, THE Collector SHALL store each Patch as a content-addressed file in the Config_Repo at `patches/<md5>.txt` where `<md5>` is the MD5 hex digest of the patch file content.
2. WHEN a Patch file has the same MD5 digest as an existing file in the Patch_Registry, THE Collector SHALL notify the user that the patch already exists in the Patch_Registry by displaying the existing patch name, the MD5 digest, and the file path `patches/<md5>.txt`, before prompting for user input.
3. WHEN presenting a Patch to the user for registration, THE Collector SHALL display a reference to the patch file at `patches/<md5>.txt` so the user can inspect the patch content.
4. WHEN presenting a Patch to the user, THE Collector SHALL display a suggested patch name generated using the pattern `<workflow-identifier>_<relative-file-path-slug>` where the slug is produced by removing the file extension, replacing path separators with underscores, replacing any character not matching `[a-zA-Z0-9_-]` with an underscore, and collapsing consecutive underscores into a single underscore.
5. WHEN presenting a Patch to the user, THE Collector SHALL prompt the user for a patch name, accepting either the suggested name (if the user presses Enter with no input) or a user-provided custom name.
6. WHEN presenting a Patch to the user, THE Collector SHALL prompt the user for a description as free-text input that is required to be non-empty.
7. IF the user-provided patch name does not match the pattern `[a-zA-Z0-9_-]+`, THEN THE Collector SHALL display a validation error message and re-prompt the user for a valid patch name without proceeding to registration.
8. IF the user-provided patch name matches an existing entry in the Patch_Registry, THEN THE Collector SHALL display a message indicating the name is already taken and re-prompt the user for a different name.
9. WHEN a Patch has the same MD5 digest as an existing file in the Patch_Registry, THE Collector SHALL offer the user the option to skip registration of that patch, and IF the user chooses to skip, THE Collector SHALL proceed to the next patch without registering the duplicate.
10. WHEN the user provides a valid, unique patch name and a non-empty description, THE Collector SHALL append an entry to `patches.yaml` with the fields: `name`, `path`, `md5sum`, and `description` using the user-provided values.
11. IF the standard input is not a TTY (non-interactive mode), THEN THE Collector SHALL display an error message indicating that interactive mode is required and exit with a non-zero status code without attempting patch registration.
12. IF the source patch file does not exist or is not writable, THEN THE Collector SHALL raise an error indicating the file path that could not be accessed and skip registration of that patch.
### Requirement 6: Output Summary

**User Story:** As a pipeline developer, I want to see a summary of collected patches after the command completes, so that I know what was generated.

#### Acceptance Criteria

1. WHEN the Collector successfully generates and registers patches, THE Collector SHALL print a summary to stdout listing one line per patch containing the patch name and its corresponding file path separated by a tab character.
2. WHEN the Collector successfully generates and registers patches, THE Collector SHALL print a final line to stdout indicating the total number of new patches created, the total number of existing patches reused, and the total number of patches skipped by the user.
3. WHEN no differences are found between the Source_Repository and the Pipeline_Source, THE Collector SHALL print a message indicating that no patches were generated and exit with status code 0.
4. WHEN the Collector completes successfully with patches generated, THE Collector SHALL exit with status code 0.
5. THE Collector SHALL write all summary output to stdout and all error messages to stderr.

### Requirement 7: Authentication

**User Story:** As a pipeline developer, I want the tool to authenticate with ICA using my existing access token, so that I can access my pipeline source.

#### Acceptance Criteria

1. WHEN the Collector needs to access the ICA API, THE Collector SHALL read the `ICAV2_ACCESS_TOKEN` environment variable and use its value as the Bearer token for all ICA API requests.
2. IF the `ICAV2_ACCESS_TOKEN` environment variable is not set or is empty, THEN THE Collector SHALL display an error message indicating the missing token and exit with a non-zero status code without making any ICA API calls, regardless of whether alternative authentication methods might be available.
3. IF the ICA API returns an authentication or authorization error during a request, THEN THE Collector SHALL halt execution immediately, display an error message indicating the authentication failure, and exit with a non-zero status code.
