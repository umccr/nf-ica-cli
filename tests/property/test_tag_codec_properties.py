"""Property-based tests for nf_ica_cli.tag_codec module.

Tests Properties 1 and 13 from the design document using Hypothesis.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nf_ica_cli.tag_codec import TagMetadata, encode_tag_message, decode_tag_message


# --- Strategies ---

# Valid git commit ID: 7-40 chars from [a-f0-9]
valid_git_commit_ids = st.text(
    alphabet="abcdef0123456789",
    min_size=7,
    max_size=40,
)

# Non-empty context strings: simple alpha strings to avoid YAML-special chars
valid_context_strings = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=30,
)

# Patch names matching [a-zA-Z0-9_-]+
valid_patch_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=50,
)

# Release status: exactly "DRAFT" or "RELEASED"
valid_release_statuses = st.sampled_from(["DRAFT", "RELEASED"])

# Workflow version description: arbitrary text (may be empty)
valid_descriptions = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,;:!?-_()",
    min_size=0,
    max_size=100,
)

# Composite strategy for valid TagMetadata objects
valid_tag_metadata = st.builds(
    TagMetadata,
    git_commit_id=valid_git_commit_ids,
    contexts=st.lists(valid_context_strings, min_size=1, max_size=5),
    patch_names=st.lists(valid_patch_names, min_size=0, max_size=5),
    release_status=valid_release_statuses,
    workflow_version_description=valid_descriptions,
)

# The five required keys for a tag message
REQUIRED_KEYS = [
    "git_commit_id",
    "contexts",
    "patch_names",
    "release_status",
    "workflow_version_description",
]


# --- Property 1: Tag codec round-trip ---
# Feature: nf-ica-cli, Property 1: For any valid TagMetadata object (containing a non-empty
# git commit ID of 7-40 hex chars, a non-empty list of context strings, a list of zero or
# more patch name strings, a release status of "DRAFT" or "RELEASED", and a workflow version
# description string), encoding the metadata to a YAML tag message and then decoding that
# message back SHALL produce a TagMetadata object with identical field values.


class TestTagCodecRoundTrip:
    """**Validates: Requirements 7.4, 7.1, 7.2, 3.2**"""

    @given(metadata=valid_tag_metadata)
    @settings(max_examples=100)
    def test_encode_decode_round_trip(self, metadata: TagMetadata) -> None:
        """Encoding then decoding a valid TagMetadata produces identical field values."""
        # Feature: nf-ica-cli, Property 1: Tag codec round-trip
        encoded = encode_tag_message(metadata)
        decoded = decode_tag_message(encoded)

        assert decoded.git_commit_id == metadata.git_commit_id
        assert decoded.contexts == metadata.contexts
        assert decoded.patch_names == metadata.patch_names
        assert decoded.release_status == metadata.release_status
        assert decoded.workflow_version_description == metadata.workflow_version_description

    @given(metadata=valid_tag_metadata)
    @settings(max_examples=100)
    def test_encode_produces_parseable_yaml(self, metadata: TagMetadata) -> None:
        """Encoding a valid TagMetadata always produces a parseable YAML document."""
        # Feature: nf-ica-cli, Property 1: Tag codec round-trip
        encoded = encode_tag_message(metadata)
        # Should not raise
        decoded = decode_tag_message(encoded)
        assert isinstance(decoded, TagMetadata)

    @given(metadata=valid_tag_metadata)
    @settings(max_examples=100)
    def test_round_trip_equality(self, metadata: TagMetadata) -> None:
        """Round-tripped TagMetadata is equal to the original."""
        # Feature: nf-ica-cli, Property 1: Tag codec round-trip
        encoded = encode_tag_message(metadata)
        decoded = decode_tag_message(encoded)

        assert decoded == metadata


# --- Property 13: Malformed tag message rejection ---
# Feature: nf-ica-cli, Property 13: For any YAML document that is missing one or more of the
# five required keys (git_commit_id, contexts, patch_names, release_status,
# workflow_version_description), or contains a value with an incorrect type (e.g., string
# where list expected), the tag message parser SHALL reject it with an error identifying
# the problematic key.


class TestMalformedTagMessageRejection:
    """**Validates: Requirements 7.3**"""

    @given(
        keys_to_remove=st.lists(
            st.sampled_from(REQUIRED_KEYS),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        metadata=valid_tag_metadata,
    )
    @settings(max_examples=100)
    def test_rejects_missing_keys(
        self, keys_to_remove: list, metadata: TagMetadata
    ) -> None:
        """A YAML document missing one or more required keys is rejected with ValueError."""
        # Feature: nf-ica-cli, Property 13: Malformed tag message rejection
        from ruamel.yaml import YAML
        from io import StringIO

        # Encode valid metadata, then remove keys
        encoded = encode_tag_message(metadata)
        yaml = YAML()
        data = yaml.load(StringIO(encoded))

        for key in keys_to_remove:
            del data[key]

        # Re-serialize to YAML string with missing keys
        stream = StringIO()
        yaml.dump(data, stream)
        malformed_message = stream.getvalue()

        with pytest.raises(ValueError) as exc_info:
            decode_tag_message(malformed_message)

        # Error message should identify at least one of the missing keys
        error_msg = str(exc_info.value)
        assert any(key in error_msg for key in keys_to_remove)

    @given(
        metadata=valid_tag_metadata,
        wrong_type_value=st.sampled_from([
            ("git_commit_id", 12345),           # int instead of str
            ("git_commit_id", ["abc123f"]),      # list instead of str
            ("contexts", "single_string"),        # str instead of list
            ("contexts", 42),                     # int instead of list
            ("patch_names", "single_string"),     # str instead of list
            ("patch_names", 99),                  # int instead of list
            ("release_status", ["DRAFT"]),        # list instead of str
            ("release_status", 1),                # int instead of str
            ("workflow_version_description", ["desc"]),  # list instead of str
            ("workflow_version_description", 100),       # int instead of str
        ]),
    )
    @settings(max_examples=100)
    def test_rejects_incorrect_types(
        self, metadata: TagMetadata, wrong_type_value: tuple
    ) -> None:
        """A YAML document with incorrect value types is rejected with ValueError."""
        # Feature: nf-ica-cli, Property 13: Malformed tag message rejection
        from ruamel.yaml import YAML
        from io import StringIO

        key, bad_value = wrong_type_value

        # Encode valid metadata, then replace a value with wrong type
        encoded = encode_tag_message(metadata)
        yaml = YAML()
        data = yaml.load(StringIO(encoded))
        data[key] = bad_value

        # Re-serialize to YAML string with bad type
        stream = StringIO()
        yaml.dump(data, stream)
        malformed_message = stream.getvalue()

        with pytest.raises(ValueError) as exc_info:
            decode_tag_message(malformed_message)

        # Error message should identify the problematic key
        error_msg = str(exc_info.value)
        assert key in error_msg

    @given(
        metadata=valid_tag_metadata,
        extra_key=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100)
    def test_rejects_unknown_keys(
        self, metadata: TagMetadata, extra_key: str
    ) -> None:
        """A YAML document with unknown keys is rejected with ValueError."""
        # Feature: nf-ica-cli, Property 13: Malformed tag message rejection
        from ruamel.yaml import YAML
        from io import StringIO

        assume(extra_key not in REQUIRED_KEYS)

        # Encode valid metadata, then add an unknown key
        encoded = encode_tag_message(metadata)
        yaml = YAML()
        data = yaml.load(StringIO(encoded))
        data[extra_key] = "unexpected_value"

        # Re-serialize to YAML string with extra key
        stream = StringIO()
        yaml.dump(data, stream)
        malformed_message = stream.getvalue()

        with pytest.raises(ValueError) as exc_info:
            decode_tag_message(malformed_message)

        # Error message should identify the unknown key
        error_msg = str(exc_info.value)
        assert extra_key in error_msg
