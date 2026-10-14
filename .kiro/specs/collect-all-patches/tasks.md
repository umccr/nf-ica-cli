# Implementation Plan: collect-all-patches

## Overview

This plan converts the `collect-all-patches` design into incremental Python coding
tasks for the `nf-ica-cli` project. Work proceeds bottom-up: pure, testable modules
(`diff_generator`, `patch_prompter`) first, then the ICA-facing `pipeline_exporter`,
then the `patch_registrar`, then the handler that wires everything together, and
finally the CLI integration. Property-based tests (Hypothesis) validate the seven
correctness properties from the design; unit and integration tests cover orchestration
and error paths.

All code follows existing conventions: subprocess-based git operation like
`git_ops.py`, content-addressed storage reuse from `patches.py`, docopt two-pass
dispatch in `cli.py`, and the `Error: [CATEGORY] message` error format. Tests live
under `tests/unit/`, `tests/property/`, and `tests/integration/`. Run tests with
`uv run pytest`.

## Tasks

- [x] 1. Create the diff generator module with file path collection
  - [x] 1.1 Implement `collect_file_paths` and the `FileDiff` dataclass
    - Create `nf_ica_cli/diff_generator.py`
    - Define the `FileDiff` dataclass (`relative_path`, `diff_content`, `is_new_file`, `is_deleted`)
    - Implement `collect_file_paths(source_dir, pipeline_dir)` returning the sorted union of relative file paths from both directories
    - Exclude any path under a `.git/` directory
    - _Requirements: 4.6, 4.8_

  - [x] 1.2 Write property test for `.git/` exclusion
    - Create `tests/property/test_diff_generator_properties.py`
    - **Property 2: .git/ exclusion** — generated file path list never references any path starting with `.git/`
    - **Validates: Requirements 4.6**
    - Tag: `# Feature: collect-all-patches, Property 2: .git/ exclusion`
    - Use Hypothesis directory-tree strategy, `@settings(max_examples=100)`

- [x] 2. Implement single-file and directory-level diff generation
  - [x] 2.1 Implement `generate_single_file_diff`
    - Add to `nf_ica_cli/diff_generator.py`
    - Run `git diff --no-index` for a source/pipeline file pair (handle new-file via `/dev/null` and deletion cases)
    - Use paths relative to the directory roots for `a/` and `b/` prefixes
    - Return `None` when files are identical (exit code 0); accept exit code 1 as "differences found"
    - Raise `RuntimeError` identifying the file pair when exit code is neither 0 nor 1
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.7_

  - [x] 2.2 Implement `generate_diffs` orchestration
    - Add to `nf_ica_cli/diff_generator.py`
    - Collect paths, diff each pair, drop `None` results, build `FileDiff` list ordered alphabetically by `relative_path`
    - Skip files with identical content (no `FileDiff` produced)
    - Return an empty list when directories are identical
    - _Requirements: 4.1, 4.4, 4.8_

  - [x] 2.3 Write property test for diff round-trip
    - Add to `tests/property/test_diff_generator_properties.py`
    - **Property 1: Diff round-trip** — applying the concatenated patch to the source dir via `git apply` reproduces the pipeline dir contents
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
    - Tag: `# Feature: collect-all-patches, Property 1: Diff round-trip`
    - Hypothesis strategy generating random file trees with add/delete/modify; `@settings(max_examples=100)`

  - [x] 2.4 Write property test for alphabetical ordering
    - Add to `tests/property/test_diff_generator_properties.py`
    - **Property 3: Alphabetical ordering of diffs** — concatenated diff headers appear in strictly ascending order by relative path
    - **Validates: Requirements 4.8**
    - Tag: `# Feature: collect-all-patches, Property 3: Alphabetical ordering of diffs`
    - `@settings(max_examples=100)`

  - [x] 2.5 Write unit tests for diff generation edge cases
    - Add to `tests/unit/test_diff_generator.py`
    - Cover new-file, deleted-file, modified-file, identical-file, and the `git diff` error (exit code > 1) path
    - _Requirements: 4.2, 4.3, 4.4, 4.7_

- [x] 3. Checkpoint - Ensure all diff generator tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the interactive patch prompter
  - [x] 4.1 Implement `suggest_patch_name` slug generation
    - Create `nf_ica_cli/patch_prompter.py`
    - Implement `suggest_patch_name(workflow_identifier, relative_path)`: strip extension, replace path separators with `_`, replace any char not in `[a-zA-Z0-9_-]` with `_`, collapse consecutive underscores, prefix with `<workflow_identifier>_`
    - _Requirements: 5.4_

  - [x] 4.2 Write property test for suggested name slug generation
    - Create `tests/property/test_patch_prompter_properties.py`
    - **Property 4: Suggested patch name slug generation** — result matches `^[a-zA-Z0-9_-]+$`, has no consecutive underscores, begins with `<workflow_identifier>_`
    - **Validates: Requirements 5.4**
    - Tag: `# Feature: collect-all-patches, Property 4: Suggested patch name slug generation`
    - Hypothesis Unicode string strategy; `@settings(max_examples=100)`

  - [x] 4.3 Implement `validate_patch_name_available` and name validation reuse
    - Add to `nf_ica_cli/patch_prompter.py`
    - Reuse `validators.validate_patch_name` for the `[a-zA-Z0-9_-]+` format check
    - Implement `validate_patch_name_available(name, existing_names)`: returns `True` only when valid and not already registered; print error and return `False` otherwise
    - _Requirements: 5.7, 5.8_

  - [x] 4.4 Write property test for patch name validation
    - Add to `tests/property/test_patch_prompter_properties.py`
    - **Property 6: Patch name validation** — accepts only non-empty `[a-zA-Z0-9_-]+` strings not already in the registry, rejects all others
    - **Validates: Requirements 5.4, 5.5**
    - Tag: `# Feature: collect-all-patches, Property 6: Patch name validation`
    - `@settings(max_examples=100)`

  - [x] 4.5 Implement `prompt_for_patch_metadata` and `PatchPromptResult`
    - Add to `nf_ica_cli/patch_prompter.py`
    - Define `PatchPromptResult` dataclass (`name`, `description`, `skip`)
    - Raise `SystemExit` when `sys.stdin.isatty()` is `False` (interactive mode required)
    - Display the relative path, the `patches/<md5>.txt` reference, and duplicate notification (existing name + MD5 + path) when the MD5 matches an existing entry
    - Offer skip for MD5 duplicates; prompt for name (default = suggested, re-prompt on invalid/taken) and non-empty description
    - _Requirements: 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 5.9, 5.11_

  - [x] 4.6 Write unit tests for interactive prompting
    - Add to `tests/unit/test_patch_prompter.py`
    - Mock `input()` and `sys.stdin.isatty()`; cover default-name acceptance, custom name, invalid-name re-prompt, taken-name re-prompt, empty-description re-prompt, duplicate skip, and non-TTY `SystemExit`
    - _Requirements: 5.2, 5.5, 5.6, 5.7, 5.8, 5.9, 5.11_

- [x] 5. Checkpoint - Ensure all prompter tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the ICA pipeline exporter
  - [x] 6.1 Implement `export_pipeline_source`
    - Create `nf_ica_cli/pipeline_exporter.py`
    - Validate `ICAV2_ACCESS_TOKEN` is set and non-empty before any ICA API call; exit non-zero with a missing-token error otherwise
    - Call `wrapica.pipelines.download_pipeline_to_directory` to download all pipeline files into `output_dir`, preserving relative structure
    - Wrap wrapica `ApiException` into `RuntimeError` with context: auth failure, pipeline-not-found (include project + pipeline id), and per-file download failure (remove temp dir, identify failed file)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 7.1, 7.2, 7.3_

  - [x] 6.2 Write unit tests for pipeline exporter
    - Create `tests/unit/test_pipeline_exporter.py`
    - Mock wrapica; cover missing-token fail-fast, auth-failure, pipeline-not-found, per-file download failure with cleanup, and successful download preserving structure
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 7.2, 7.3_

- [x] 7. Implement the patch registrar
  - [x] 7.1 Implement `register_collected_patches` and `CollectedPatch`
    - Create `nf_ica_cli/patch_registrar.py`
    - Define `CollectedPatch` dataclass (`name`, `description`, `relative_path`, `md5sum`, `is_new`, `was_skipped`)
    - For each `FileDiff`: write content to a temp file, compute MD5 via `patches.compute_md5`, detect existing-registry match, prompt via `prompt_for_patch_metadata`, and either record skip or call `patches.register_patch`
    - Raise an error identifying the file path when the temp patch file is missing or not writable, and skip that patch
    - Append registered entries (`name`, `path`, `md5sum`, `description`) to `patches.yaml` via `yaml_io`
    - _Requirements: 5.1, 5.2, 5.9, 5.10, 5.12_

  - [x] 7.2 Write property test for content-addressed storage
    - Create `tests/property/test_patch_registrar_properties.py`
    - **Property 5: Content-addressed storage correctness** — file stored at `patches/<md5>.txt` where `<md5> == hashlib.md5(content.encode()).hexdigest()`, and no new file is written when MD5 already exists
    - **Validates: Requirements 5.1, 5.2**
    - Tag: `# Feature: collect-all-patches, Property 5: Content-addressed storage correctness`
    - Hypothesis random byte-content strategy; `@settings(max_examples=100)`

  - [x] 7.3 Write unit tests for the patch registrar
    - Create `tests/unit/test_patch_registrar.py`
    - Mock the prompter; cover new-patch registration, duplicate reuse, user-skip, unwritable temp-file skip, and `patches.yaml` append
    - _Requirements: 5.1, 5.9, 5.10, 5.12_

- [x] 8. Checkpoint - Ensure exporter and registrar tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement the handler orchestration and summary output
  - [x] 9.1 Implement `handle_collect_all_patches`
    - Create `nf_ica_cli/handlers/collect_all_patches.py`
    - Extract `--repo-uri`, `--commit-id`, `--project-id`, `--pipeline-id` from args
    - Fail-fast if `ICAV2_ACCESS_TOKEN` is unset/empty (before network calls)
    - Create clone and export temp dirs with `tempfile.mkdtemp`; clone via `git_ops.clone_at_commit` (surface URI, commit, timeout, and auth errors); export via `export_pipeline_source`
    - Generate diffs via `generate_diffs`; if none, print the no-patches message to stdout and return with status 0
    - Register via `register_collected_patches`; clean up both temp dirs in a `finally` block using `shutil.rmtree(..., ignore_errors=True)`, logging a warning to stderr on failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.6, 6.3, 6.4, 7.1, 7.2_

  - [x] 9.2 Implement the summary output formatting
    - Add summary logic to `nf_ica_cli/handlers/collect_all_patches.py`
    - Print one tab-separated `name<TAB>path` line per registered (non-skipped) patch to stdout
    - Print a final line with counts of new, reused, and skipped patches
    - Route all summary output to stdout and all error messages to stderr
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

  - [x] 9.3 Write property test for summary output correctness
    - Create `tests/property/test_collect_summary_properties.py`
    - **Property 7: Summary output correctness** — exactly one tab-separated line per registered patch, and final-line counts satisfy `new_count + reused_count + skipped_count == total diffs processed`
    - **Validates: Requirements 6.1, 6.2**
    - Tag: `# Feature: collect-all-patches, Property 7: Summary output correctness`
    - Hypothesis random `CollectedPatch` list strategy (mix new/reused/skipped); `@settings(max_examples=100)`

  - [x] 9.4 Write unit tests for handler orchestration and error paths
    - Create `tests/unit/test_collect_all_patches_handler.py`
    - Mock `clone_at_commit`, `export_pipeline_source`, `generate_diffs`, `register_collected_patches`; verify call sequence and argument passing
    - Cover missing-token fail-fast, clone failure, export/API failure, no-diffs path, and temp-dir cleanup on success and error
    - _Requirements: 2.2, 2.3, 2.4, 3.6, 6.3, 7.2_

- [x] 10. Wire the subcommand into the CLI
  - [x] 10.1 Add `collect-all-patches` to the docopt dispatch
    - Edit `nf_ica_cli/cli.py`
    - Add the `collect-all-patches` usage string to `_SUBCMD_USAGE` with the four required `--argument=<value>` options and `--help`
    - Add the command to the top-level Commands list and dispatch with a lazy import of `handle_collect_all_patches`
    - Ensure missing/unrecognized args produce stderr errors and exit code 1, and `--help` exits 0
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 10.2 Write unit tests for CLI argument parsing
    - Create `tests/unit/test_cli_collect_all_patches.py`
    - Verify all four args are parsed, missing args error with exit 1, unrecognized arg errors with exit 1, and `--help` shows all four options and exits 0
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 11. Add the end-to-end integration test
  - [x] 11.1 Write integration test for the full flow
    - Create `tests/integration/test_collect_all_patches_integration.py`
    - Build a local git repo and a mock pipeline export dir; mock wrapica responses and `input()`; simulate a TTY
    - Verify the complete flow from handler invocation to `patches.yaml` update and summary output
    - _Requirements: 4.1, 5.1, 5.10, 6.1, 6.2_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation across module boundaries.
- Property tests validate the seven universal correctness properties from the design; unit tests cover specific examples and error conditions.
- Reuse existing infrastructure: `git_ops.clone_at_commit`, `patches.compute_md5`, `patches.register_patch`, `validators.validate_patch_name`, and `yaml_io` load/save.
- Run the suite with `uv run pytest`; property tests use Hypothesis with `@settings(max_examples=100)`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5", "4.1", "6.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "6.2"] },
    { "id": 5, "tasks": ["4.4", "4.5"] },
    { "id": 6, "tasks": ["4.6", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "9.1"] },
    { "id": 8, "tasks": ["9.2"] },
    { "id": 9, "tasks": ["9.3", "9.4", "10.1"] },
    { "id": 10, "tasks": ["10.2", "11.1"] }
  ]
}
```
