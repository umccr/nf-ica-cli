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
git diff modules/local/esvee/main.nf > /tmp/esvee_high_mem.patch
```

This produces output like:

```diff
diff --git a/modules/local/esvee/main.nf b/modules/local/esvee/main.nf
index abb63cc9..4bd48057 100644
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
git diff --no-index /dev/null conf/icav2.config > /tmp/add_icav2_config.patch
```

This produces output like:

```diff
diff --git a/dev/null b/conf/icav2.config
new file mode 100644
index 0000000..a1b2c3d
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

---

### Step 3: Create the Deployment Tag

Once the workflow version is registered and patches are in place, create an annotated git tag
that encodes the deployment metadata. This tag is what GitHub Actions reads during deployment.

```bash
nf-ica make-workflow-version \
  --workflow-name oncoanalyser \
  --workflow-version-tag 2.4.0 \
  --workflow-version-git-commit-id abc1234def5678 \
  --workflow-version-context production \
  --workflow-version-context development \
  --workflow-patch-name oncoanalyser_esvee_to_higher_mem \
  --workflow-patch-name standard_icav2_wrapica_patch \
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
