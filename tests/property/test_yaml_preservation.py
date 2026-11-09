# Feature: nf-ica-cli, Property 2: YAML comment and formatting preservation
"""Property-based tests for YAML comment and formatting preservation.

**Validates: Requirements 2.8, 4.7, 5.11, 8.8**

Tests that for any YAML document containing comments and specific formatting
(key order, blank lines, quote styles), loading it with ruamel.yaml, modifying
a value within the document, and writing it back preserves all comments and
the relative ordering of unmodified keys.
"""

import re
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nf_ica_cli.yaml_io import load_yaml, save_yaml


# --- Strategies ---

# Generate valid YAML key names (simple alphanumeric to avoid YAML special chars)
yaml_key_st = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)

# Generate simple YAML-safe string values that won't be auto-parsed as
# non-string types (avoid bare numbers, true/false/null, etc.)
# No trailing spaces since YAML strips trailing whitespace from unquoted scalars.
yaml_value_st = st.from_regex(r"[a-z][a-zA-Z0-9_]{0,15}[a-z0-9]", fullmatch=True)


@st.composite
def yaml_document_with_comments(draw):
    """Generate a YAML document string with comments and formatting.

    Produces a document with:
    - A top-level comment
    - Between 3 and 8 key-value pairs with unique keys
    - Inline comments on some keys
    - Between-key comments on some keys
    - Preserves insertion order
    """
    num_keys = draw(st.integers(min_value=3, max_value=8))

    # Generate unique keys
    keys = draw(
        st.lists(
            yaml_key_st,
            min_size=num_keys,
            max_size=num_keys,
            unique=True,
        )
    )

    values = draw(
        st.lists(
            yaml_value_st,
            min_size=num_keys,
            max_size=num_keys,
        )
    )

    # Decide which keys get inline comments
    inline_comment_flags = draw(
        st.lists(
            st.booleans(),
            min_size=num_keys,
            max_size=num_keys,
        )
    )

    # Decide which keys get a preceding between-key comment
    between_comment_flags = draw(
        st.lists(
            st.booleans(),
            min_size=num_keys,
            max_size=num_keys,
        )
    )

    # Build the YAML document
    lines = ["# Top-level document comment"]

    for i, (key, value, has_inline, has_between) in enumerate(
        zip(keys, values, inline_comment_flags, between_comment_flags)
    ):
        if has_between and i > 0:
            lines.append(f"# Comment before {key}")
        if has_inline:
            lines.append(f"{key}: {value}  # inline comment for {key}")
        else:
            lines.append(f"{key}: {value}")

    lines.append("")  # trailing newline
    return "\n".join(lines), keys, values


def extract_comments(text: str) -> list[str]:
    """Extract all comment strings from a YAML document."""
    comments = []
    for line in text.split("\n"):
        # Full-line comments
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(stripped)
        # Inline comments
        elif "#" in line:
            # Find inline comment (after value, preceded by at least two spaces)
            match = re.search(r"  (#.+)$", line)
            if match:
                comments.append(match.group(1).strip())
    return comments


def extract_key_order(text: str) -> list[str]:
    """Extract the order of top-level keys from a YAML document."""
    keys = []
    for line in text.split("\n"):
        # Skip comments and blank lines
        if line.strip().startswith("#") or not line.strip():
            continue
        # Match top-level key (no leading whitespace)
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:", line)
        if match:
            keys.append(match.group(1))
    return keys


# --- Property Tests ---


class TestYamlCommentPreservation:
    """Property tests for YAML comment and formatting preservation."""

    @given(data=yaml_document_with_comments())
    @settings(max_examples=100)
    def test_comments_preserved_after_modify_and_save(
        self, data, tmp_path_factory
    ):
        """Loading YAML, modifying a value, and saving preserves all comments.

        For any YAML document with comments, the load→modify→save cycle
        must preserve every comment on unmodified keys (top-level,
        between-key, and inline) and all full-line comments.
        """
        yaml_content, keys, values = data

        # We need at least 2 keys so we can modify one and check the rest
        assume(len(keys) >= 2)

        tmp_path = tmp_path_factory.mktemp("yaml_preserve")
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)

        # Identify comments NOT associated with the key we'll modify (keys[0])
        # Full-line comments and inline comments on other keys should survive
        modified_key = keys[0]
        expected_comments = []
        for line in yaml_content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                # Full-line comments are always preserved
                expected_comments.append(stripped)
            elif "#" in line:
                # Inline comment — only expect preservation if not on modified key
                match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:", line)
                if match and match.group(1) != modified_key:
                    inline = re.search(r"  (#.+)$", line)
                    if inline:
                        expected_comments.append(inline.group(1).strip())

        assume(len(expected_comments) > 0)

        # Load, modify, save
        doc = load_yaml(yaml_file)
        doc[modified_key] = "modified_value"
        save_yaml(yaml_file, doc)

        # Extract comments from result
        result_content = yaml_file.read_text()
        result_comments = extract_comments(result_content)

        # All expected comments must be present in result
        assert set(expected_comments) <= set(result_comments), (
            f"Comments lost during round-trip.\n"
            f"Missing: {set(expected_comments) - set(result_comments)}"
        )

    @given(data=yaml_document_with_comments())
    @settings(max_examples=100)
    def test_key_order_preserved_after_modify_and_save(
        self, data, tmp_path_factory
    ):
        """Loading YAML, modifying a value, and saving preserves key order.

        For any YAML document, the relative ordering of all keys
        (including modified ones) must be preserved after a load→modify→save
        cycle.
        """
        yaml_content, keys, values = data

        assume(len(keys) >= 2)

        tmp_path = tmp_path_factory.mktemp("yaml_order")
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)

        # Load, modify one value, save
        doc = load_yaml(yaml_file)
        doc[keys[0]] = "modified_value"
        save_yaml(yaml_file, doc)

        # Extract key orders
        result_content = yaml_file.read_text()
        original_key_order = extract_key_order(yaml_content)
        result_key_order = extract_key_order(result_content)

        # Key order must be identical
        assert original_key_order == result_key_order, (
            f"Key order changed during round-trip.\n"
            f"Original: {original_key_order}\n"
            f"Result:   {result_key_order}"
        )

    @given(data=yaml_document_with_comments())
    @settings(max_examples=100)
    def test_unmodified_values_preserved(
        self, data, tmp_path_factory
    ):
        """Loading YAML, modifying one value, preserves all other values.

        For any YAML document, modifying a single key's value must not
        affect any other key's value.
        """
        yaml_content, keys, values = data

        assume(len(keys) >= 2)

        tmp_path = tmp_path_factory.mktemp("yaml_values")
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)

        # Load, modify first key, save
        doc = load_yaml(yaml_file)
        doc[keys[0]] = "modified_value"
        save_yaml(yaml_file, doc)

        # Reload and verify unmodified keys
        reloaded = load_yaml(yaml_file)

        # First key should have the new value
        assert reloaded[keys[0]] == "modified_value"

        # All other keys should retain their original values
        for key, original_value in zip(keys[1:], values[1:]):
            assert reloaded[key] == original_value, (
                f"Value for key '{key}' changed unexpectedly.\n"
                f"Expected: {original_value}\n"
                f"Got:      {reloaded[key]}"
            )
