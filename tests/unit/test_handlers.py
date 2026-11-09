"""Unit tests for subcommand handlers."""

from pathlib import Path

import pytest

from nf_ica_cli.config import AppConfig, IcaConfig
from nf_ica_cli.handlers.register_patch import handle_register_patch
from nf_ica_cli.patches import PatchEntry, compute_md5
from nf_ica_cli.yaml_io import load_yaml


def _make_app_config(config_repo: Path, patches: list = None) -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        config_repo=config_repo,
        workflows=[],
        contexts=[],
        ica_config=IcaConfig(tenants=[], default_nextflow_version=""),
        pipelines=[],
        patches=patches or [],
    )


def _make_args(file_path: str, name: str, description: str) -> dict:
    """Create a minimal docopt-style args dict for register-patch."""
    return {
        "--file": file_path,
        "--name": name,
        "--description": description,
        "register-patch": True,
    }


class TestHandleRegisterPatch:
    """Tests for handle_register_patch handler."""

    def test_registers_new_patch_and_updates_yaml(self, tmp_path):
        """Successfully registers a patch and writes it to patches.yaml."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()
        (config_repo / "patches").mkdir()

        source = tmp_path / "my_patch.diff"
        source.write_text("--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n")

        args = _make_args(str(source), "my-patch", "A test patch")
        config = _make_app_config(config_repo)

        handle_register_patch(args, config, config_repo)

        # Verify patches.yaml was created with the entry
        patches_path = config_repo / "config" / "patches.yaml"
        assert patches_path.exists()

        data = load_yaml(patches_path)
        assert len(data["patches"]) == 1

        entry = data["patches"][0]
        assert entry["name"] == "my-patch"
        assert entry["description"] == "A test patch"
        assert entry["md5sum"] == compute_md5(source)
        assert entry["path"] == f"patches/{entry['md5sum']}.txt"

    def test_appends_to_existing_patches_yaml(self, tmp_path):
        """Appends to an existing patches.yaml without overwriting."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()
        (config_repo / "patches").mkdir()

        # Create existing patches.yaml with one entry
        patches_path = config_repo / "config" / "patches.yaml"
        from nf_ica_cli.yaml_io import save_yaml

        existing_data = {
            "patches": [
                {
                    "name": "existing-patch",
                    "path": "patches/aaa111.txt",
                    "md5sum": "aaa111",
                    "description": "Existing patch",
                }
            ]
        }
        save_yaml(patches_path, existing_data)

        # Create existing patch file and register it in config
        existing_patches = [
            PatchEntry(
                name="existing-patch",
                path="patches/aaa111.txt",
                md5sum="aaa111",
                description="Existing patch",
            )
        ]

        source = tmp_path / "new_patch.diff"
        source.write_text("new patch content\n")

        args = _make_args(str(source), "new-patch", "A new patch")
        config = _make_app_config(config_repo, patches=existing_patches)

        handle_register_patch(args, config, config_repo)

        # Verify both entries exist
        data = load_yaml(patches_path)
        assert len(data["patches"]) == 2
        assert data["patches"][0]["name"] == "existing-patch"
        assert data["patches"][1]["name"] == "new-patch"

    def test_exits_on_invalid_patch_name(self, tmp_path):
        """Exits with SystemExit for invalid patch name."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()

        source = tmp_path / "patch.diff"
        source.write_text("content")

        args = _make_args(str(source), "invalid name!", "desc")
        config = _make_app_config(config_repo)

        with pytest.raises(SystemExit, match="Invalid patch name"):
            handle_register_patch(args, config, config_repo)

    def test_exits_on_name_collision(self, tmp_path):
        """Exits with SystemExit when patch name already exists."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()

        source = tmp_path / "patch.diff"
        source.write_text("content")

        existing_patches = [
            PatchEntry(
                name="taken-name",
                path="patches/abc.txt",
                md5sum="abc",
                description="existing",
            )
        ]

        args = _make_args(str(source), "taken-name", "desc")
        config = _make_app_config(config_repo, patches=existing_patches)

        with pytest.raises(SystemExit, match="already registered"):
            handle_register_patch(args, config, config_repo)

    def test_exits_on_missing_source_file(self, tmp_path):
        """Exits with SystemExit when source file doesn't exist."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()

        args = _make_args(str(tmp_path / "nonexistent.diff"), "my-patch", "desc")
        config = _make_app_config(config_repo)

        with pytest.raises(SystemExit, match="not found"):
            handle_register_patch(args, config, config_repo)

    def test_copies_file_to_content_addressed_path(self, tmp_path):
        """Patch file is copied to patches/<md5sum>.txt."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()
        (config_repo / "patches").mkdir()

        source = tmp_path / "my_patch.diff"
        source.write_text("unique content here\n")
        md5 = compute_md5(source)

        args = _make_args(str(source), "content-patch", "test desc")
        config = _make_app_config(config_repo)

        handle_register_patch(args, config, config_repo)

        dest = config_repo / "patches" / f"{md5}.txt"
        assert dest.exists()
        assert dest.read_text() == source.read_text()

    def test_skips_copy_when_md5_exists(self, tmp_path):
        """Does not overwrite existing file when MD5 matches."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()
        (config_repo / "patches").mkdir()

        source = tmp_path / "patch.diff"
        source.write_text("shared content")
        md5 = compute_md5(source)

        # Pre-existing file with same content
        existing_dest = config_repo / "patches" / f"{md5}.txt"
        existing_dest.write_text("shared content")

        existing_patches = [
            PatchEntry(
                name="other-patch",
                path=f"patches/{md5}.txt",
                md5sum=md5,
                description="other",
            )
        ]

        args = _make_args(str(source), "new-name", "new desc")
        config = _make_app_config(config_repo, patches=existing_patches)

        handle_register_patch(args, config, config_repo)

        # File was not overwritten (content still the same)
        assert existing_dest.read_text() == "shared content"

        # patches.yaml has the new entry
        data = load_yaml(config_repo / "config" / "patches.yaml")
        assert data["patches"][0]["name"] == "new-name"
        assert data["patches"][0]["md5sum"] == md5

    def test_handles_empty_patches_yaml(self, tmp_path):
        """Works when patches.yaml exists but has null patches key."""
        config_repo = tmp_path / "config_repo"
        config_repo.mkdir()
        (config_repo / "config").mkdir()
        (config_repo / "patches").mkdir()

        # Create patches.yaml with null content
        patches_path = config_repo / "config" / "patches.yaml"
        patches_path.write_text("patches:\n")

        source = tmp_path / "patch.diff"
        source.write_text("patch content\n")

        args = _make_args(str(source), "first-patch", "First patch")
        config = _make_app_config(config_repo)

        handle_register_patch(args, config, config_repo)

        data = load_yaml(patches_path)
        assert len(data["patches"]) == 1
        assert data["patches"][0]["name"] == "first-patch"
