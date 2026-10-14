"""Property-based tests for config repo discovery.

Tests Property 8 from the design document using Hypothesis.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.config import find_config_repo


# --- Strategies ---

# Valid directory name characters (safe for filesystem)
dir_name_chars = "abcdefghijklmnopqrstuvwxyz0123456789"

# Strategy for generating valid directory names
dir_names = st.text(
    alphabet=dir_name_chars,
    min_size=1,
    max_size=12,
)


# --- Property 8: Config repo discovery ---
# Feature: nf-ica-cli, Property 8: For any directory tree where exactly one ancestor
# directory (including the starting directory) contains `config/workflows.yaml`,
# invoking the config repo finder from any subdirectory at or below that ancestor
# SHALL return the path to that ancestor.


class TestConfigRepoDiscovery:
    """**Validates: Requirements 1.2**"""

    @given(
        prefix_dirs=st.lists(dir_names, min_size=0, max_size=3, unique=True),
        suffix_dirs=st.lists(dir_names, min_size=0, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_finds_config_repo_from_any_subdirectory(
        self, prefix_dirs: list, suffix_dirs: list
    ) -> None:
        """Config repo is found from any subdirectory at or below the ancestor.

        Given a directory structure:
          tmp / prefix_dirs... / CONFIG_ROOT / suffix_dirs... / CWD

        Where CONFIG_ROOT contains config/workflows.yaml, calling find_config_repo()
        with CWD set to the deepest nested directory SHALL return CONFIG_ROOT.
        """
        # Feature: nf-ica-cli, Property 8: Config repo discovery
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Build the config repo root at some level below tmp
            config_root = tmp_dir
            for d in prefix_dirs:
                config_root = config_root / d
            config_root.mkdir(parents=True, exist_ok=True)

            # Create config/workflows.yaml at the config root
            config_dir = config_root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "workflows.yaml").write_text("workflows: []\n")

            # Build subdirectories below the config root
            cwd = config_root
            for d in suffix_dirs:
                cwd = cwd / d
            cwd.mkdir(parents=True, exist_ok=True)

            # Patch Path.cwd to return our constructed CWD
            with patch("nf_ica_cli.config.Path.cwd", return_value=cwd):
                result = find_config_repo()

            assert result == config_root.resolve()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(
        suffix_dirs=st.lists(dir_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_finds_config_repo_when_cwd_is_config_root(
        self, suffix_dirs: list
    ) -> None:
        """Config repo is found when CWD is the config repo root itself.

        This tests the base case: CWD is exactly the directory containing
        config/workflows.yaml.
        """
        # Feature: nf-ica-cli, Property 8: Config repo discovery
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            config_root = tmp_dir
            # Create config/workflows.yaml at the config root
            config_dir = config_root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "workflows.yaml").write_text("workflows: []\n")

            with patch("nf_ica_cli.config.Path.cwd", return_value=config_root):
                result = find_config_repo()

            assert result == config_root.resolve()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(
        depth=st.integers(min_value=1, max_value=5),
        dir_name=dir_names,
    )
    @settings(max_examples=100)
    def test_not_found_when_no_config_exists(
        self, depth: int, dir_name: str
    ) -> None:
        """SystemExit is raised when no ancestor contains config/workflows.yaml.

        For any directory tree without config/workflows.yaml anywhere,
        find_config_repo() SHALL raise SystemExit.
        """
        # Feature: nf-ica-cli, Property 8: Config repo discovery
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Build nested dirs without any config/workflows.yaml
            cwd = tmp_dir
            for i in range(depth):
                cwd = cwd / f"{dir_name}_{i}"
            cwd.mkdir(parents=True, exist_ok=True)

            with patch("nf_ica_cli.config.Path.cwd", return_value=cwd):
                with pytest.raises(SystemExit):
                    find_config_repo()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(
        prefix_dirs=st.lists(dir_names, min_size=0, max_size=3, unique=True),
        suffix_dirs=st.lists(dir_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_returns_nearest_ancestor_with_config(
        self, prefix_dirs: list, suffix_dirs: list
    ) -> None:
        """Config repo discovery returns the nearest ancestor containing config/workflows.yaml.

        When multiple ancestors contain config/workflows.yaml, the closest one
        to the CWD is returned (since traversal goes upward from CWD).
        """
        # Feature: nf-ica-cli, Property 8: Config repo discovery
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Build prefix path from tmp
            outer_root = tmp_dir
            for d in prefix_dirs:
                outer_root = outer_root / d
            outer_root.mkdir(parents=True, exist_ok=True)

            # Place config/workflows.yaml at the outer root
            outer_config = outer_root / "config"
            outer_config.mkdir(parents=True, exist_ok=True)
            (outer_config / "workflows.yaml").write_text("workflows: []\n")

            # Build an inner config repo below
            inner_root = outer_root
            for d in suffix_dirs:
                inner_root = inner_root / d
            inner_root.mkdir(parents=True, exist_ok=True)

            inner_config = inner_root / "config"
            inner_config.mkdir(parents=True, exist_ok=True)
            (inner_config / "workflows.yaml").write_text("workflows: []\n")

            # CWD is at the inner root - should find the inner root first
            with patch("nf_ica_cli.config.Path.cwd", return_value=inner_root):
                result = find_config_repo()

            assert result == inner_root.resolve()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
