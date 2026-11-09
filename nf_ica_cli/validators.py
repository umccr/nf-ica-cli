"""Input validators for nf-ica CLI.

Each validator returns True on success and raises ValueError on failure
with a descriptive message identifying what was invalid and what's expected.
"""

import re
from typing import List


# Patterns
_GIT_COMMIT_ID_PATTERN = re.compile(r"^[a-f0-9]{7,40}$")
_PATCH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_RELEASE_STATUSES = ("DRAFT", "RELEASED")


def validate_git_commit_id(value: str) -> bool:
    """Validate that value is a valid abbreviated or full git commit hash.

    Accepts 7-40 lowercase hexadecimal characters [a-f0-9].

    Args:
        value: The string to validate.

    Returns:
        True if valid.

    Raises:
        ValueError: If the value is not a valid git commit ID.
    """
    if not _GIT_COMMIT_ID_PATTERN.match(value):
        raise ValueError(
            f"Invalid git commit ID: '{value}'. "
            f"Expected 7-40 lowercase hexadecimal characters [a-f0-9]."
        )
    return True


def validate_patch_name(value: str) -> bool:
    """Validate that value is a valid patch name.

    Accepts non-empty strings containing only [a-zA-Z0-9_-].

    Args:
        value: The string to validate.

    Returns:
        True if valid.

    Raises:
        ValueError: If the value is not a valid patch name.
    """
    if not value:
        raise ValueError(
            "Invalid patch name: name must not be empty. "
            "Expected non-empty string containing only alphanumeric characters, "
            "hyphens, and underscores [a-zA-Z0-9_-]."
        )
    if not _PATCH_NAME_PATTERN.match(value):
        raise ValueError(
            f"Invalid patch name: '{value}'. "
            f"Expected only alphanumeric characters, hyphens, and underscores [a-zA-Z0-9_-]."
        )
    return True


def validate_release_status(value: str) -> bool:
    """Validate that value is a valid release status.

    Accepts only "DRAFT" or "RELEASED" (case-sensitive).

    Args:
        value: The string to validate.

    Returns:
        True if valid.

    Raises:
        ValueError: If the value is not a valid release status.
    """
    if value not in _VALID_RELEASE_STATUSES:
        raise ValueError(
            f"Invalid release status: '{value}'. "
            f"Expected one of: {', '.join(_VALID_RELEASE_STATUSES)}."
        )
    return True


def validate_context(value: str, defined_contexts: List[str]) -> bool:
    """Validate that value is a member of the defined contexts.

    Args:
        value: The context name to validate.
        defined_contexts: List of valid context names from contexts.yaml.

    Returns:
        True if valid.

    Raises:
        ValueError: If the value is not in the defined contexts list.
    """
    if value not in defined_contexts:
        raise ValueError(
            f"Invalid context: '{value}'. "
            f"Available contexts: {', '.join(sorted(defined_contexts))}."
        )
    return True
