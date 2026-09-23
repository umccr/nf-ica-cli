"""End-to-end integration test for the collect-all-patches subcommand.

Exercises ``handle_collect_all_patches`` from handler invocation all the way
through to a ``patches.yaml`` update and the summary output, with only the two
genuinely external boundaries mocked:

* **The ICA pipeline export** — ``download_pipeline_to_directory`` (the wrapica
  function imported into :mod:`nf_ica_cli.pipeline_exporter`) is replaced with a
  fake that populates the export directory with files that differ from the
  source repository (a modification, an addition, and a deletion) so real diffs
  are produced.
* **Interactive input** — ``builtins.input`` is patched to feed patch
  names/descriptions, and ``sys.stdin.isatty`` (looked up in
  :mod:`nf_ica_cli.patch_prompter`) is forced to ``True`` so the prompter treats
  the run as interactive.

Everything else is real:

* A REAL local git repository is initialised and committed so
  ``git_ops.clone_at_commit`` clones it (via a ``file://`` URI) and checks out
  the created commit.
* ``diff_generator.generate_diffs`` runs a real ``git diff --no-index`` against
  the two directory trees, producing real unified diffs.
* ``patch_registrar.register_collected_patches`` writes real
  ``patches/<md5>.txt`` files into the config repo and appends real entries to
  ``config/patches.yaml`` via the real ``yaml_io`` load/save.

Validates: Requirements 4.1, 5.1, 5.10, 6.1, 6.2
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.config import AppConfig, IcaConfig
from nf_ica_cli.handlers.collect_all_patches import handle_collect_all_patches
from nf_ica_cli.patches import compute_md5
from nf_ica_cli.yaml_io import load_yaml

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PIPELINE_ID = "22222222-2222-2222-2222-222222222222"

# The source repository's initial contents. These are committed as the baseline
# that the (mocked) pipeline export is diffed against.
_SOURCE_FILES = {
    "main.nf": "workflow {\n    take_input()\n}\n",
    "conf/ica.config": "params {\n    cpus = 1\n}\n",
    "docs/removed.md": "This file only exists in the source repo.\n",
}

# The pipeline export's contents. Relative to _SOURCE_FILES this:
#   * MODIFIES  main.nf and conf/ica.config,
#   * ADDS      nextflow.config (new file — exists only in the export),
#   * DELETES   docs/removed.md (exists only in the source repo).
_PIPELINE_FILES = {
    "main.nf": "workflow {\n    take_input()\n    extra_step()\n}\n",
    "conf/ica.config": "params {\n    cpus = 4\n}\n",
    "nextflow.config": "process.executor = 'awsbatch'\n",
}


def _make_app_config(config_repo: Path) -> AppConfig:
    """Build a minimal AppConfig with empty patches and workflows.

    Mirrors the construction used in tests/unit/test_collect_all_patches_handler.py
    (``_make_app_config``) but with empty ``patches``/``workflows`` lists as the
    task requires.
    """
    return AppConfig(
        config_repo=config_repo,
        workflows=[],
        contexts=[],
        ica_config=IcaConfig(tenants=[], default_nextflow_version=""),
        pipelines=[],
        patches=[],
    )


def _write_tree(root: Path, files: dict) -> None:
    """Write a {relative_path: content} mapping into ``root``."""
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def _init_source_repo(repo_dir: Path) -> str:
    """Initialise a real git repo in ``repo_dir`` and commit the source files.

    Returns the commit SHA of the single commit so the handler can check it out.
    Git identity is provided per-command so the test does not depend on (or
    mutate) any global git configuration.
    """
    repo_dir.mkdir(parents=True, exist_ok=True)
    _write_tree(repo_dir, _SOURCE_FILES)

    env_args = [
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Integration Test",
    ]

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *env_args, *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True,
        )

    _git("init")
    _git("add", "-A")
    _git("commit", "-m", "Initial source commit")
    result = _git("rev-parse", "HEAD")
    return result.stdout.strip()


def _fake_download_pipeline_to_directory(pipeline_id: str, output_directory: Path):
    """Stand-in for wrapica's download; populates the export dir with files.

    Signature mirrors how :mod:`nf_ica_cli.pipeline_exporter` calls the real
    function (``pipeline_id=..., output_directory=...``). It writes the
    ``_PIPELINE_FILES`` tree into the provided output directory so the real diff
    generator produces genuine add/modify/delete diffs.
    """
    _write_tree(Path(output_directory), _PIPELINE_FILES)


@pytest.fixture
def token(monkeypatch):
    """Provide a valid ICAV2_ACCESS_TOKEN for the duration of a test."""
    monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "an-integration-token")


def test_full_flow_writes_patches_updates_yaml_and_prints_summary(
    tmp_path, token, capsys
):
    """Run the whole flow end-to-end and assert on the real side effects.

    Asserts:
      * three real ``patches/<md5>.txt`` files are written to the config repo,
        each named by the MD5 of its own content (Req 5.1),
      * ``config/patches.yaml`` gains three entries with ``name``/``path``/
        ``md5sum``/``description`` from the user's input (Req 5.10),
      * the produced diffs are real unified diffs (Req 4.1),
      * the summary output contains one ``name<TAB>path`` line per registered
        patch plus a final counts line (Req 6.1, 6.2).
    """
    # --- Arrange: a real source git repo and a config repo. ---
    source_repo = tmp_path / "source_repo"
    commit_id = _init_source_repo(source_repo)
    repo_uri = source_repo.as_uri()  # file:// URI for a local clone.

    config_repo = tmp_path / "config_repo"
    (config_repo / "config").mkdir(parents=True)
    config = _make_app_config(config_repo)

    args = {
        "--repo-uri": repo_uri,
        "--commit-id": commit_id,
        "--project-id": PROJECT_ID,
        "--pipeline-id": PIPELINE_ID,
        "collect-all-patches": True,
    }

    # The diffs are produced in alphabetical order by relative path:
    #   conf/ica.config, docs/removed.md, main.nf, nextflow.config
    # Supply a custom name for the first prompt and accept the suggested default
    # (empty response) for the rest; every description is non-empty. Two input()
    # calls per patch: [name, description].
    input_responses = iter(
        [
            "ica_config_patch",  # custom name for conf/ica.config
            "Bump cpus to 4",  # description
            "",  # accept suggested name for docs/removed.md
            "Drop the removed doc",  # description
            "",  # accept suggested name for main.nf
            "Add an extra step",  # description
            "",  # accept suggested name for nextflow.config
            "Pin the awsbatch executor",  # description
        ]
    )

    def _fake_input(_prompt: str = "") -> str:
        return next(input_responses)

    # --- Act: run the handler with only the two external boundaries mocked. ---
    with patch(
        "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
        side_effect=_fake_download_pipeline_to_directory,
    ), patch(
        "nf_ica_cli.patch_prompter.sys.stdin.isatty",
        return_value=True,
    ), patch(
        "builtins.input",
        side_effect=_fake_input,
    ):
        result = handle_collect_all_patches(args, config, config_repo)

    # The handler returns None (exit status 0) on success.
    assert result is None

    # --- Assert: patch files written to config_repo/patches/<md5>.txt. ---
    patches_dir = config_repo / "patches"
    patch_files = sorted(patches_dir.glob("*.txt"))
    # Four files differ (modify x2, add x1, delete x1) -> four patch files.
    assert len(patch_files) == 4, (
        f"expected 4 content-addressed patch files, found "
        f"{[p.name for p in patch_files]}"
    )

    # Each patch file is named by the MD5 of its own content (Req 5.1).
    for patch_file in patch_files:
        assert patch_file.stem == compute_md5(patch_file), (
            f"patch file {patch_file.name} is not named by its content MD5"
        )
        # The stored content is a real unified diff (Req 4.1): it contains the
        # git diff header and hunk markers.
        content = patch_file.read_text()
        assert content.startswith("diff --git "), content
        assert "@@" in content, content

    # --- Assert: patches.yaml gained the four entries (Req 5.10). ---
    patches_yaml_path = config_repo / "config" / "patches.yaml"
    assert patches_yaml_path.exists()
    patches_data = load_yaml(patches_yaml_path)
    entries = patches_data["patches"]
    assert len(entries) == 4

    # Every entry carries the four required fields, and each field is populated.
    for entry in entries:
        assert set(entry.keys()) == {"name", "path", "md5sum", "description"}
        assert entry["name"]
        assert entry["description"]
        # path is the content-addressed registry path and matches md5sum.
        assert entry["path"] == f"patches/{entry['md5sum']}.txt"
        # The referenced patch file actually exists on disk.
        assert (config_repo / entry["path"]).exists()

    names = {entry["name"] for entry in entries}
    descriptions = {entry["description"] for entry in entries}
    # The custom name supplied for the first prompt is used verbatim.
    assert "ica_config_patch" in names
    # The custom descriptions the user supplied are all recorded.
    assert {
        "Bump cpus to 4",
        "Drop the removed doc",
        "Add an extra step",
        "Pin the awsbatch executor",
    } == descriptions

    # --- Assert: the summary output (Req 6.1, 6.2). ---
    captured = capsys.readouterr()
    out_lines = captured.out.splitlines()

    # One tab-separated name<TAB>path line per registered patch (Req 6.1).
    tab_lines = [line for line in out_lines if "\t" in line]
    assert len(tab_lines) == 4
    for entry in entries:
        expected_line = f"{entry['name']}\t{entry['path']}"
        assert expected_line in tab_lines

    # A final counts line reporting new/reused/skipped (Req 6.2). All four are
    # brand new here, none reused, none skipped.
    summary_lines = [line for line in out_lines if line.startswith("Summary:")]
    assert len(summary_lines) == 1
    summary = summary_lines[0]
    assert "4 new" in summary
    assert "0 reused" in summary
    assert "0 skipped" in summary
