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
