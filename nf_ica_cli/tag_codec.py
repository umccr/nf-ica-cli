"""Tag codec for annotated git tag message serialization and deserialization.

Encodes and decodes deployment metadata as YAML in annotated git tag messages.
The tag message schema uses exactly 5 keys:
  - git_commit_id (string, non-empty)
  - contexts (list of one or more strings)
  - patch_names (list of zero or more strings)
  - release_status (string, "DRAFT" or "RELEASED")
  - workflow_version_description (string, may be empty)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import List

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


_REQUIRED_KEYS = frozenset({
    "git_commit_id",
    "contexts",
    "patch_names",
    "release_status",
    "workflow_version_description",
})


@dataclass
class TagMetadata:
    """Deployment metadata stored in an annotated git tag message."""

    git_commit_id: str
    contexts: List[str]
    patch_names: List[str]
    release_status: str  # "DRAFT" | "RELEASED"
    workflow_version_description: str


def encode_tag_message(metadata: TagMetadata) -> str:
    """Serialize TagMetadata to a YAML string for an annotated tag message.

    Produces a YAML document with exactly 5 keys in a deterministic order.

    Args:
        metadata: The TagMetadata to serialize.

    Returns:
        A YAML-formatted string suitable for use as an annotated tag message.
    """
    yaml = YAML()
    yaml.default_flow_style = False

    data = {
        "git_commit_id": metadata.git_commit_id,
        "contexts": metadata.contexts,
        "patch_names": metadata.patch_names,
        "release_status": metadata.release_status,
        "workflow_version_description": metadata.workflow_version_description,
    }

    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def decode_tag_message(message: str) -> TagMetadata:
    """Deserialize a YAML annotated tag message to TagMetadata.

    Validates that all 5 required keys are present with correct types.
    Rejects messages with missing keys, unknown keys, or type mismatches.

    Args:
        message: The YAML string from the annotated tag message.

    Returns:
        A TagMetadata object with the parsed values.

    Raises:
        ValueError: If the message is missing keys, has unknown keys,
            or contains values with incorrect types.
    """
    yaml = YAML()

    try:
        data = yaml.load(StringIO(message))
    except YAMLError as e:
        raise ValueError(
            f"Invalid tag message: failed to parse YAML. {e}"
        ) from e

    if data is None:
        raise ValueError(
            "Invalid tag message: empty document. "
            f"Expected keys: {', '.join(sorted(_REQUIRED_KEYS))}."
        )

    if not isinstance(data, dict):
        raise ValueError(
            "Invalid tag message: expected a YAML mapping at the top level."
        )

    # Check for unknown keys
    present_keys = set(data.keys())
    unknown_keys = present_keys - _REQUIRED_KEYS
    if unknown_keys:
        raise ValueError(
            f"Invalid tag message: unknown key(s): {', '.join(sorted(unknown_keys))}. "
            f"Expected only: {', '.join(sorted(_REQUIRED_KEYS))}."
        )

    # Check for missing keys
    missing_keys = _REQUIRED_KEYS - present_keys
    if missing_keys:
        raise ValueError(
            f"Invalid tag message: missing key(s): {', '.join(sorted(missing_keys))}. "
            f"All of these keys are required: {', '.join(sorted(_REQUIRED_KEYS))}."
        )

    # Validate types
    _validate_field_type(data, "git_commit_id", str, "non-empty string")
    _validate_field_type(data, "contexts", list, "list of strings")
    _validate_field_type(data, "patch_names", list, "list of strings")
    _validate_field_type(data, "release_status", str, "string")
    _validate_field_type(data, "workflow_version_description", str, "string")

    # Validate non-empty git_commit_id
    if not data["git_commit_id"]:
        raise ValueError(
            "Invalid tag message: 'git_commit_id' must be a non-empty string."
        )

    # Validate contexts is non-empty list
    if len(data["contexts"]) == 0:
        raise ValueError(
            "Invalid tag message: 'contexts' must contain at least one element."
        )

    # Validate all items in contexts are strings
    for i, item in enumerate(data["contexts"]):
        if not isinstance(item, str):
            raise ValueError(
                f"Invalid tag message: 'contexts[{i}]' must be a string, "
                f"got {type(item).__name__}."
            )

    # Validate all items in patch_names are strings
    for i, item in enumerate(data["patch_names"]):
        if not isinstance(item, str):
            raise ValueError(
                f"Invalid tag message: 'patch_names[{i}]' must be a string, "
                f"got {type(item).__name__}."
            )

    return TagMetadata(
        git_commit_id=data["git_commit_id"],
        contexts=list(data["contexts"]),
        patch_names=list(data["patch_names"]),
        release_status=data["release_status"],
        workflow_version_description=data["workflow_version_description"],
    )


def make_tag_name(workflow_name: str, version_tag: str) -> str:
    """Generate a tag name with the current UTC timestamp.

    Format: <workflow-name>/<version-tag>__YYYYMMDDHHMMSS

    Args:
        workflow_name: The workflow name (e.g., "oncoanalyser").
        version_tag: The version tag (e.g., "2.2.0").

    Returns:
        A formatted tag name string.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{workflow_name}/{version_tag}__{timestamp}"


def _validate_field_type(
    data: dict, key: str, expected_type: type, type_description: str
) -> None:
    """Validate that a field has the expected type.

    Args:
        data: The parsed YAML dictionary.
        key: The key to check.
        expected_type: The expected Python type.
        type_description: Human-readable description of the expected type.

    Raises:
        ValueError: If the field value does not match the expected type.
    """
    value = data[key]
    if not isinstance(value, expected_type):
        raise ValueError(
            f"Invalid tag message: '{key}' must be {type_description}, "
            f"got {type(value).__name__}."
        )
