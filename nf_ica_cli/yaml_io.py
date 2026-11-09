"""YAML I/O module with comment and formatting preservation.

Uses ruamel.yaml to load and save YAML documents while preserving
comments, key order, and quote styles.
"""

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


def load_yaml(path: Path) -> dict:
    """Load a YAML file preserving comments and formatting.

    Args:
        path: Path to the YAML file to load.

    Returns:
        Parsed YAML data as a dict (CommentedMap).

    Raises:
        SystemExit: If the file is not found or contains invalid YAML.
    """
    yaml = YAML()
    yaml.preserve_quotes = True

    if not path.exists():
        raise SystemExit(
            f"Error: [FILE NOT FOUND] Cannot read YAML file\n"
            f"  Context: {path}"
        )

    try:
        with open(path) as f:
            data = yaml.load(f)
    except YAMLError as e:
        # Extract line/column info from ruamel.yaml error if available
        location = _format_yaml_error_location(e)
        raise SystemExit(
            f"Error: [YAML PARSE] Invalid YAML syntax\n"
            f"  Context: {path}{location}"
        ) from e

    return data


def save_yaml(path: Path, data: dict) -> None:
    """Write data to a YAML file preserving comments and formatting.

    Args:
        path: Path to the YAML file to write.
        data: YAML data (typically a CommentedMap from load_yaml).
    """
    yaml = YAML()
    yaml.preserve_quotes = True

    with open(path, "w") as f:
        yaml.dump(data, f)


def _format_yaml_error_location(error: YAMLError) -> str:
    """Extract line/column information from a ruamel.yaml error.

    Returns a formatted string like ' (line 5, column 3)' or empty
    string if location info is not available.
    """
    # ruamel.yaml errors may have a problem_mark attribute
    mark = getattr(error, "problem_mark", None)
    if mark is not None:
        # mark.line and mark.column are 0-indexed
        return f" (line {mark.line + 1}, column {mark.column + 1})"
    return ""
