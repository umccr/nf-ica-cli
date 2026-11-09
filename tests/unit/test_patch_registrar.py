"""Unit tests for nf_ica_cli.patch_registrar module.

Covers ``register_collected_patches`` and ``CollectedPatch`` for the
collect-all-patches subcommand:

* new-patch registration (a new content-addressed file is written and an entry
  is appended to ``patches.yaml``),
* duplicate reuse (an existing MD5 means no new file is written but the entry is
  still registered/appended),
* user-skip (the prompter returns ``skip=True`` — nothing is registered and no
  YAML entry is appended),
* unwritable temp-file skip (an OSError on the temp file path is reported to
  stderr and that patch is skipped while processing continues), and
* the ``patches.yaml`` append shape (``name``, ``path``, ``md5sum``,
  ``description``).

The interactive prompter is not driven by a real TTY in tests, so
``prompt_for_patch_metadata`` is mocked at its import site in
``nf_ica_cli.patch_registrar`` to return ``PatchPromptResult`` objects.

Validates: Requirements 5.1, 5.9, 5.10, 5.12
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from nf_ica_cli.diff_generator import FileDiff
from nf_ica_cli.patch_prompter import PatchPromptResult
from nf_ica_cli.patch_registrar import CollectedPatch, register_collected_patches
from nf_ica_cli.patches import PatchEntry
from nf_ica_cli.yaml_io import load_yaml

WORKFLOW_ID = "myworkflow"


def _make_diff(relative_path: str, content: str) -> FileDiff:
    """Build a FileDiff whose diff_content is exactly ``content``.

    The MD5 the registrar computes is the MD5 of the temp file's bytes, which
    are ``content`` encoded as UTF-8, so tests can predict the digest with
    ``_md5_of(content)``.
    """
    return FileDiff(
        relative_path=relative_path,
        diff_content=content,
        is_new_file=True,
        is_deleted=False,
    )


def _md5_of(content: str) -> str:
    """MD5 hex digest of ``content`` encoded as UTF-8 (matches temp-file bytes)."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


@pytest.fixture
def config_repo(tmp_path):
    """A config repo with a config/ directory (patches.yaml created lazily)."""
    repo = tmp_path / "config_repo"
    (repo / "config").mkdir(parents=True)
    (repo / "patches").mkdir()
    return repo


class TestNewPatchRegistration:
    """A brand-new patch writes a file and appends to patches.yaml.

    Validates: Requirements 5.1, 5.10.
    """

    def test_new_patch_writes_file_and_appends_entry(self, config_repo):
        content = "--- /dev/null\n+++ b/conf/ica.config\n@@ -0,0 +1 @@\n+params {}\n"
        diff = _make_diff("conf/ica.config", content)
        md5sum = _md5_of(content)

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            return_value=PatchPromptResult(
                name="myworkflow_conf_ica",
                description="ICA config overrides",
                skip=False,
            ),
        ):
            results = register_collected_patches(
                diffs=[diff],
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=[],
            )

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, CollectedPatch)
        assert result.name == "myworkflow_conf_ica"
        assert result.description == "ICA config overrides"
        assert result.relative_path == "conf/ica.config"
        assert result.md5sum == md5sum
        assert result.is_new is True
        assert result.was_skipped is False

        # (5.1) The content-addressed file was written under patches/<md5>.txt.
        patch_file = config_repo / "patches" / f"{md5sum}.txt"
        assert patch_file.exists()
        assert patch_file.read_text() == content

        # (5.10) An entry was appended to patches.yaml.
        patches_path = config_repo / "config" / "patches.yaml"
        assert patches_path.exists()
        data = load_yaml(patches_path)
        assert len(data["patches"]) == 1
        entry = data["patches"][0]
        assert entry["name"] == "myworkflow_conf_ica"
        assert entry["path"] == f"patches/{md5sum}.txt"
        assert entry["md5sum"] == md5sum
        assert entry["description"] == "ICA config overrides"

    def test_prompter_receives_workflow_identifier(self, config_repo):
        """The workflow identifier is threaded through to the prompter."""
        diff = _make_diff("main.nf", "workflow-diff\n")

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            return_value=PatchPromptResult(
                name="myworkflow_main", description="main", skip=False
            ),
        ) as mock_prompt:
            register_collected_patches(
                diffs=[diff],
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=[],
            )

        assert mock_prompt.call_count == 1
        kwargs = mock_prompt.call_args.kwargs
        assert kwargs["workflow_identifier"] == WORKFLOW_ID
        assert kwargs["relative_path"] == "main.nf"
        assert kwargs["md5sum"] == _md5_of("workflow-diff\n")


class TestDuplicateReuse:
    """A matching MD5 reuses the existing file but is still registered.

    Validates: Requirements 5.1, 5.10.
    """

    def test_duplicate_md5_reuses_file_and_still_appends(self, config_repo):
        content = "shared-diff-content\n"
        md5sum = _md5_of(content)

        # Pre-seed the registry and the on-disk file for the same content.
        existing_path = f"patches/{md5sum}.txt"
        existing_file = config_repo / existing_path
        existing_file.write_text(content)
        original_mtime = existing_file.stat().st_mtime_ns

        existing = [
            PatchEntry(
                name="old-name",
                path=existing_path,
                md5sum=md5sum,
                description="pre-existing",
            )
        ]

        diff = _make_diff("conf/base.config", content)

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            return_value=PatchPromptResult(
                name="new-name", description="new desc", skip=False
            ),
        ):
            results = register_collected_patches(
                diffs=[diff],
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=existing,
            )

        assert len(results) == 1
        result = results[0]
        # is_new is False because the MD5 already existed in the registry.
        assert result.is_new is False
        assert result.was_skipped is False
        assert result.md5sum == md5sum
        assert result.name == "new-name"

        # No new file was written: the existing file is untouched.
        assert existing_file.stat().st_mtime_ns == original_mtime
        assert existing_file.read_text() == content

        # The entry is still appended to patches.yaml (reuse still registers).
        patches_path = config_repo / "config" / "patches.yaml"
        data = load_yaml(patches_path)
        assert len(data["patches"]) == 1
        entry = data["patches"][0]
        assert entry["name"] == "new-name"
        assert entry["path"] == existing_path
        assert entry["md5sum"] == md5sum


class TestUserSkip:
    """When the user skips, nothing is registered or appended.

    Validates: Requirements 5.9.
    """

    def test_skip_does_not_register_or_append(self, config_repo):
        content = "duplicate-content\n"
        md5sum = _md5_of(content)

        existing = [
            PatchEntry(
                name="existing",
                path=f"patches/{md5sum}.txt",
                md5sum=md5sum,
                description="already here",
            )
        ]

        diff = _make_diff("conf/dup.config", content)

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            return_value=PatchPromptResult(name="", description="", skip=True),
        ):
            with patch("nf_ica_cli.patch_registrar.register_patch") as mock_register:
                results = register_collected_patches(
                    diffs=[diff],
                    workflow_identifier=WORKFLOW_ID,
                    config_repo=config_repo,
                    existing_patches=existing,
                )

        # register_patch is never called for a skipped patch.
        mock_register.assert_not_called()

        assert len(results) == 1
        result = results[0]
        assert result.was_skipped is True
        assert result.name == ""
        assert result.description == ""
        assert result.relative_path == "conf/dup.config"
        assert result.md5sum == md5sum

        # No patches.yaml was created/appended for a skip-only run.
        patches_path = config_repo / "config" / "patches.yaml"
        assert not patches_path.exists()

    def test_skip_then_register_continues_to_next(self, config_repo):
        """A skipped patch does not stop later patches from registering."""
        skip_content = "skip-me\n"
        keep_content = "keep-me\n"
        keep_md5 = _md5_of(keep_content)

        existing = [
            PatchEntry(
                name="dup",
                path=f"patches/{_md5_of(skip_content)}.txt",
                md5sum=_md5_of(skip_content),
                description="dup",
            )
        ]

        diffs = [
            _make_diff("skip.txt", skip_content),
            _make_diff("keep.txt", keep_content),
        ]

        # First diff is skipped, second is registered.
        prompt_results = [
            PatchPromptResult(name="", description="", skip=True),
            PatchPromptResult(name="keep-name", description="keep desc", skip=False),
        ]

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            side_effect=prompt_results,
        ):
            results = register_collected_patches(
                diffs=diffs,
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=existing,
            )

        assert len(results) == 2
        assert results[0].was_skipped is True
        assert results[1].was_skipped is False
        assert results[1].name == "keep-name"

        # Only the non-skipped patch is written and appended.
        assert (config_repo / "patches" / f"{keep_md5}.txt").exists()
        data = load_yaml(config_repo / "config" / "patches.yaml")
        assert len(data["patches"]) == 1
        assert data["patches"][0]["name"] == "keep-name"


class TestUnwritableTempFileSkip:
    """A temp-file access failure reports to stderr and skips that patch.

    Validates: Requirements 5.12.
    """

    def test_tempfile_oserror_skips_patch_and_reports(self, config_repo, capsys):
        diff = _make_diff("conf/ica.config", "content\n")

        with patch(
            "nf_ica_cli.patch_registrar.tempfile.NamedTemporaryFile",
            side_effect=OSError("read-only file system"),
        ):
            results = register_collected_patches(
                diffs=[diff],
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=[],
            )

        # The patch is skipped: no result recorded, nothing written or appended.
        assert results == []
        assert not (config_repo / "config" / "patches.yaml").exists()

        # An error identifying the file path is written to stderr (5.12).
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "conf/ica.config" in captured.err

    def test_tempfile_error_does_not_stop_later_patches(self, config_repo):
        """A failing temp file for one diff still lets a later diff register."""
        bad_diff = _make_diff("bad.txt", "bad\n")
        good_diff = _make_diff("good.txt", "good\n")
        good_md5 = _md5_of("good\n")

        real_named_temp = __import__("tempfile").NamedTemporaryFile
        call_state = {"count": 0}

        def flaky_named_temp(*args, **kwargs):
            call_state["count"] += 1
            if call_state["count"] == 1:
                raise OSError("disk full")
            return real_named_temp(*args, **kwargs)

        with patch(
            "nf_ica_cli.patch_registrar.tempfile.NamedTemporaryFile",
            side_effect=flaky_named_temp,
        ):
            with patch(
                "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
                return_value=PatchPromptResult(
                    name="good-name", description="good desc", skip=False
                ),
            ):
                results = register_collected_patches(
                    diffs=[bad_diff, good_diff],
                    workflow_identifier=WORKFLOW_ID,
                    config_repo=config_repo,
                    existing_patches=[],
                )

        # Only the second (good) diff produced a result.
        assert len(results) == 1
        assert results[0].name == "good-name"
        assert results[0].relative_path == "good.txt"
        assert (config_repo / "patches" / f"{good_md5}.txt").exists()


class TestPatchesYamlAppend:
    """patches.yaml gains one entry per registered patch with the right shape.

    Validates: Requirements 5.10.
    """

    def test_appends_to_existing_patches_yaml(self, config_repo):
        # Seed an existing patches.yaml with one entry.
        patches_path = config_repo / "config" / "patches.yaml"
        from nf_ica_cli.yaml_io import save_yaml

        save_yaml(
            patches_path,
            {
                "patches": [
                    {
                        "name": "pre-existing",
                        "path": "patches/deadbeef.txt",
                        "md5sum": "deadbeef",
                        "description": "seeded",
                    }
                ]
            },
        )

        content = "new-diff\n"
        md5sum = _md5_of(content)
        diff = _make_diff("workflow.nf", content)

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            return_value=PatchPromptResult(
                name="appended", description="appended desc", skip=False
            ),
        ):
            register_collected_patches(
                diffs=[diff],
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=[],
            )

        data = load_yaml(patches_path)
        assert len(data["patches"]) == 2
        # Original entry preserved.
        assert data["patches"][0]["name"] == "pre-existing"
        # New entry appended with all four fields.
        appended = data["patches"][1]
        assert appended == {
            "name": "appended",
            "path": f"patches/{md5sum}.txt",
            "md5sum": md5sum,
            "description": "appended desc",
        }

    def test_multiple_patches_all_appended(self, config_repo):
        diffs = [
            _make_diff("a.txt", "content-a\n"),
            _make_diff("b.txt", "content-b\n"),
        ]

        prompt_results = [
            PatchPromptResult(name="patch-a", description="desc a", skip=False),
            PatchPromptResult(name="patch-b", description="desc b", skip=False),
        ]

        with patch(
            "nf_ica_cli.patch_registrar.prompt_for_patch_metadata",
            side_effect=prompt_results,
        ):
            results = register_collected_patches(
                diffs=diffs,
                workflow_identifier=WORKFLOW_ID,
                config_repo=config_repo,
                existing_patches=[],
            )

        assert len(results) == 2
        data = load_yaml(config_repo / "config" / "patches.yaml")
        names = [entry["name"] for entry in data["patches"]]
        assert names == ["patch-a", "patch-b"]
