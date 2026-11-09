"""Unit tests for the YAML I/O module."""

import pytest
from pathlib import Path

from nf_ica_cli.yaml_io import load_yaml, save_yaml


class TestLoadYaml:
    """Tests for load_yaml function."""

    def test_loads_simple_yaml(self, tmp_path: Path):
        """Load a simple YAML file and verify contents."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: hello\nversion: 1\n")

        result = load_yaml(yaml_file)

        assert result["name"] == "hello"
        assert result["version"] == 1

    def test_preserves_comments_in_memory(self, tmp_path: Path):
        """Load YAML with comments — comments are preserved in the data structure."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "# Top comment\n"
            "name: hello  # inline comment\n"
            "items:\n"
            "  - one\n"
            "  - two\n"
        )

        result = load_yaml(yaml_file)

        assert result["name"] == "hello"
        assert result["items"] == ["one", "two"]

    def test_file_not_found_raises_system_exit(self, tmp_path: Path):
        """Missing file should raise SystemExit with clear error message."""
        missing = tmp_path / "nonexistent.yaml"

        with pytest.raises(SystemExit) as exc_info:
            load_yaml(missing)

        error_msg = str(exc_info.value)
        assert "FILE NOT FOUND" in error_msg
        assert "nonexistent.yaml" in error_msg

    def test_invalid_yaml_raises_system_exit(self, tmp_path: Path):
        """Invalid YAML syntax should raise SystemExit with parse error details."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("items:\n  - valid\n  bad indent: broken\n  : invalid")

        with pytest.raises(SystemExit) as exc_info:
            load_yaml(yaml_file)

        error_msg = str(exc_info.value)
        assert "YAML PARSE" in error_msg
        assert "bad.yaml" in error_msg

    def test_preserves_quoted_strings(self, tmp_path: Path):
        """Quoted strings should be preserved in memory."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text('name: "hello"\nversion: \'1.0\'\n')

        result = load_yaml(yaml_file)

        assert result["name"] == "hello"
        assert result["version"] == "1.0"

    def test_loads_nested_structure(self, tmp_path: Path):
        """Load nested YAML structures correctly."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "workflows:\n"
            "  - name: test\n"
            "    versions:\n"
            "      - tag: '1.0'\n"
            "        contexts:\n"
            "          - production\n"
        )

        result = load_yaml(yaml_file)

        assert result["workflows"][0]["name"] == "test"
        assert result["workflows"][0]["versions"][0]["tag"] == "1.0"
        assert result["workflows"][0]["versions"][0]["contexts"] == ["production"]


class TestSaveYaml:
    """Tests for save_yaml function."""

    def test_saves_simple_data(self, tmp_path: Path):
        """Save a simple dict and verify file content."""
        yaml_file = tmp_path / "output.yaml"

        save_yaml(yaml_file, {"name": "hello", "version": 1})

        content = yaml_file.read_text()
        assert "name: hello" in content
        assert "version: 1" in content

    def test_round_trip_preserves_comments(self, tmp_path: Path):
        """Load-modify-save cycle should preserve comments."""
        yaml_file = tmp_path / "test.yaml"
        original = (
            "# Top-level comment\n"
            "name: hello  # name comment\n"
            "items:\n"
            "  - one\n"
            "  - two\n"
        )
        yaml_file.write_text(original)

        data = load_yaml(yaml_file)
        data["name"] = "world"
        save_yaml(yaml_file, data)

        result = yaml_file.read_text()
        assert "# Top-level comment" in result
        assert "# name comment" in result
        assert "name: world" in result

    def test_round_trip_preserves_key_order(self, tmp_path: Path):
        """Load-save cycle should preserve key ordering."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("zebra: 1\nalpha: 2\nmiddle: 3\n")

        data = load_yaml(yaml_file)
        save_yaml(yaml_file, data)

        result = yaml_file.read_text()
        lines = [l for l in result.strip().split("\n") if l]
        assert lines[0].startswith("zebra")
        assert lines[1].startswith("alpha")
        assert lines[2].startswith("middle")

    def test_round_trip_preserves_quotes(self, tmp_path: Path):
        """Load-save cycle should preserve quote styles."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text('name: "quoted"\nplain: unquoted\n')

        data = load_yaml(yaml_file)
        save_yaml(yaml_file, data)

        result = yaml_file.read_text()
        assert '"quoted"' in result

    def test_creates_parent_directories_not_needed(self, tmp_path: Path):
        """Save to an existing directory works fine."""
        yaml_file = tmp_path / "sub" / "output.yaml"
        yaml_file.parent.mkdir(parents=True)

        save_yaml(yaml_file, {"key": "value"})

        assert yaml_file.exists()
        assert "key: value" in yaml_file.read_text()
