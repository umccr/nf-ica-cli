# nf-ica-cli

CLI toolkit for orchestrating Nextflow pipeline deployments to Illumina Connected Analytics (ICA).

## Installation

```bash
pip install -e ".[dev]"
```

## Configuration

The CLI needs access to the [nf-ica](https://github.com/UMCCR/nf-ica) configuration repository. Set the `NF_ICA_REPO_PATH` environment variable to the root of your local clone:

```bash
export NF_ICA_REPO_PATH=/path/to/nf-ica
```

If `NF_ICA_REPO_PATH` is not set, the CLI falls back to searching upward from the current working directory for a directory containing `config/workflows.yaml`.

## Usage

```bash
nf-ica --help
```

The typical workflow for deploying a Nextflow pipeline to ICA follows these steps:

1. Register the workflow version
2. Create and register any patches
3. Create the deployment tag
4. Check the pipeline ID

---

### Step 1: Add a Workflow Version

Register a new version of a workflow in `workflows.yaml`. This records which commit and contexts
the version targets, and optionally which ICA Nextflow engine version to use.

```bash
nf-ica add-workflow-version \
  --workflow-name oncoanalyser \
  --workflow-repo-uri https://github.com/nf-core/oncoanalyser \
  --workflow-version-tag 2.4.0 \
  --workflow-version-git-commit-id abc1234def5678 \
  --workflow-version-context production \
  --workflow-version-context development \
  --workflow-ica-nextflow-version 25.10
```

This appends the version to the workflow's entry in `config/workflows.yaml`. If the workflow doesn't
exist yet, it creates a new workflow entry.

---

### Step 2: Create and Register Patches

Patches allow you to modify the workflow source before deployment (e.g. adjusting resource labels,
injecting ICA-specific configuration). Patches use standard unified diff format.

#### Creating a patch for an existing file

From inside the workflow repository, make your changes to the file and then generate the patch:

```bash
git diff modules/local/esvee/main.nf \
  | sed -E '/^index [0-9a-f]+\.\.[0-9a-f]+( [0-7]+)?$/d' \
  > /tmp/esvee_high_mem.patch
```

The `sed` filter strips the volatile git `index <hash>..<hash>` header line so the patch
content-addresses the same way `collect-all-patches` stores it (see the note below).

This produces output like:

```diff
diff --git a/modules/local/esvee/main.nf b/modules/local/esvee/main.nf
--- a/modules/local/esvee/main.nf
+++ b/modules/local/esvee/main.nf
@@ -1,6 +1,6 @@
 process ESVEE {
     tag "${meta.id}"
-    label 'process_high'
+    label 'process_high_memory'
 
     conda "${moduleDir}/environment.yml"
```

#### Creating a patch for a new file

Use `git diff --no-index` to generate a patch that creates a file from scratch:

```bash
git diff --no-index /dev/null conf/icav2.config \
  | sed -E '/^index [0-9a-f]+\.\.[0-9a-f]+( [0-7]+)?$/d' \
  > /tmp/add_icav2_config.patch
```

This produces output like:

```diff
diff --git a/conf/icav2.config b/conf/icav2.config
new file mode 100644
--- /dev/null
+++ b/conf/icav2.config
@@ -0,0 +1,12 @@
+// ICAv2-specific process label mappings
+process {
+    withLabel: 'process_low' {
+        pod = [annotation: 'scheduler.illumina.com/presetSize: standard-small']
+    }
+    withLabel: 'process_medium' {
+        pod = [annotation: 'scheduler.illumina.com/presetSize: standard-medium']
+    }
+    withLabel: 'process_high' {
+        pod = [annotation: 'scheduler.illumina.com/presetSize: standard-large']
+    }
+}
```

#### Registering the patch

Once you have a patch file, register it with the CLI:

```bash
nf-ica register-patch \
  --file /tmp/esvee_high_mem.patch \
  --name oncoanalyser_esvee_to_higher_mem \
  --description "Esvee should use the process_high_memory label instead of process_high"
```

This copies the patch into the `patches/` directory (named by its MD5 hash) and adds an entry
to `config/patches.yaml`.

> **Note on content-addressing and the `collect-all-patches` command**
>
> Patches are content-addressed: the file is stored as `patches/<md5>.txt` and duplicate
> content is detected by matching MD5s. The `collect-all-patches` command (which generates
> patches automatically by diffing a workflow repo against its exported ICA pipeline source)
> **strips the volatile git `index <hash>..<hash>` header line** before storing and hashing
> each diff. Git's abbreviated blob hashes on that line vary between otherwise-identical
> patches (and even differ in hex width), so dropping it lets the same logical change produce
> the same MD5 every time — which is what makes duplicate detection reliable. Removing the
> `index` line is safe because `git apply` does not need it.
>
> This is why the manual `git diff` examples above pipe through
> `sed -E '/^index [0-9a-f]+\.\.[0-9a-f]+( [0-7]+)?$/d'`: stripping the `index` line at
> creation time makes a hand-made patch content-address identically to the same change
> produced by `collect-all-patches`. If you register a patch that still has its `index` line,
> it will simply hash under a different MD5 — it still applies fine, it just won't be
> recognised as a duplicate of the stripped version.

---

### Step 3: Create the Deployment Tag

Once the workflow version is registered and patches are in place, create an annotated git tag
that encodes the deployment metadata. This tag is what GitHub Actions reads during deployment.

```bash
nf-ica deploy-workflow-version \
  --workflow-name oncoanalyser \
  --workflow-version-tag 2.4.0 \
  --workflow-version-git-commit-id abc1234def5678 \
  --workflow-version-context production \
  --workflow-version-context development \
  --workflow-patch-name oncoanalyser_esvee_to_higher_mem \
  --workflow-patch-name standard_icav2_config \
  --release-status DRAFT \
  --workflow-version-description "Oncoanalyser 2.4.0 with ICA resource patches"
```

This creates the annotated git tag and pushes it to the remote, triggering the GitHub Actions
deployment workflow automatically.

---

### Step 4: Check the Pipeline ID

Once the GitHub Actions deployment completes, the pipeline ID for each context is published on the
[nf-ica releases page](https://github.com/UMCCR/nf-ica/releases). Find the release matching your
tag to see the ICA pipeline identifiers assigned to each project.

To update the release status once you've validated the pipeline:

```bash
nf-ica update-workflow-version-release-status \
  --workflow-name oncoanalyser \
  --workflow-version-tag 2.4.0 \
  --release-status RELEASED
```
---

## Iterative Development

The steps above build a deployment up from individual patches you author by hand. When you have
instead iterated on a pipeline *directly in ICA* — editing a draft pipeline in the development
project until it works — you can go the other way and **recover the full set of patches from the
live pipeline** with `collect-all-patches`. It clones the original workflow source at a known
commit, exports the current ICA pipeline source, diffs the two trees, and interactively registers
each difference as a patch in the content-addressed store.

This is the quickest way to capture the ICA-specific edits (resource labels, `conf/icav2.config`,
pod annotations, and so on) that accumulated while you were iterating, without diffing files by
hand.

### Prerequisites

- `ICAV2_ACCESS_TOKEN` must be set to a valid ICA access token (the command fails fast if it is
  missing or empty, before any network call):

  ```bash
  export ICAV2_ACCESS_TOKEN="<value_from_secret>"
  ```

- `NF_ICA_REPO_PATH` must point at your local `nf-ica` config repo clone (see
  [Configuration](#configuration)), because registered patches are written into its `patches/`
  directory and `config/patches.yaml`.
- You must run the command in an **interactive terminal** — it prompts for a name and description
  for each patch, so it refuses to run when stdin is not a TTY.

### Running collect-all-patches

```bash
nf-ica collect-all-patches \
  --repo-uri https://github.com/nf-core/oncoanalyser \
  --commit-id abc1234def5678 \
  --project-id <development_project_id> \
  --pipeline-id <pipeline_id>
```

| Flag | Meaning |
| --- | --- |
| `--repo-uri` | Git URI of the original (upstream) workflow source. |
| `--commit-id` | Git commit SHA to clone and diff against — use the commit the ICA pipeline was built from. |
| `--project-id` | ICA project UUID that contains the pipeline (e.g. the development project). |
| `--pipeline-id` | ICA pipeline UUID to export the source from (found in `config/ica_pipelines.yaml`). |

### Interactive registration

For every file that differs between the source commit and the exported ICA pipeline, the command
shows the changed file and the registry path it would be stored under, then prompts you:

- **Name** — press Enter to accept the suggested name (derived from the matching workflow in
  `config/workflows.yaml`, or the repo basename), or type your own. Names must be unique and match
  `[a-zA-Z0-9_-]+`; it re-prompts on an invalid or already-used name.
- **Description** — a non-empty free-text description.

If a diff's content already exists in the registry (same MD5), the command tells you which existing
patch it matches and offers to **skip** it (`Skip this patch? [Y/n]`), so re-running the command
does not create duplicates.

Each registered diff is stored as `patches/<md5>.txt` and appended to `config/patches.yaml`. As
with manually created patches, the volatile git `index <hash>..<hash>` header line is stripped
before the diff is hashed and stored, so the same logical change always content-addresses to the
same MD5 (see the note under [Step 2](#step-2-create-and-register-patches)).

### Reading the summary

When it finishes, the command prints one tab-separated `name<TAB>patches/<md5>.txt` line per
registered patch, followed by a counts line, for example:

```
oncoanalyser_esvee_to_higher_mem	patches/edd8c4ac7a8adf0a628b236dac789c0f.txt
standard_icav2_config	patches/38bb618394c99f71eb8ea96afa5b5d2b.txt
Summary: 1 new, 1 reused, 0 skipped.
```

- **new** — the content was not in the registry before and a new `patches/<md5>.txt` file was written.
- **reused** — the content already existed (same MD5) and was registered under a new name without copying a file.
- **skipped** — you chose to skip a duplicate at the prompt.

If the source commit and the exported pipeline are identical, nothing is registered and the command
reports that no patches were generated.

Once the patches are collected, continue from [Step 3](#step-3-create-the-deployment-tag) to tag and
deploy the version that bundles them.
