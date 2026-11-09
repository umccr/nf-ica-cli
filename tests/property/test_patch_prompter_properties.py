"""Property-based tests for nf_ica_cli.patch_prompter module.

Tests correctness properties from the collect-all-patches design document
using Hypothesis.
"""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.patch_prompter import suggest_patch_name


# --- Strategies ---

# A workflow identifier constrained to the patch-name character set
# [a-zA-Z0-9_-], matching the Property 4 statement in the design document.
_workflow_identifier_body = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=32,
)

# A workflow identifier that ends in an underscore is a degenerate case: the
# design's Property 4 requires the result to (b) contain no consecutive
# underscores AND (c) begin with "<workflow_identifier>_". For an identifier
# ending in "_" those two clauses are mutually unsatisfiable — the mandatory
# "_" separator would form a "__" run with the identifier's own trailing "_".
# A real workflow identifier does not end in "_", so we exclude that case while
# still exercising the prefix boundary (identifiers may contain underscores
# internally, and slugs may start/end with characters that meet the prefix).
#
# Likewise, an identifier that itself contains a "__" run is degenerate:
# suggest_patch_name passes the identifier through verbatim (it only collapses
# underscores *within the generated slug*), so a "__" already present in the
# identifier would surface in the result and violate clause (b) through no
# fault of the slug logic. We exclude that too — the property under test is
# about the name the function builds, not about pre-existing malformed inputs.
_workflow_identifier = (
    _workflow_identifier_body.map(lambda s: s.rstrip("_"))
    .filter(lambda s: len(s) > 0)
    .filter(lambda s: "__" not in s)
)

# An arbitrary Unicode string for the relative file path. Hypothesis' default
# text() strategy draws from the full Unicode range, exercising the slug's
# disallowed-character replacement across arbitrary code points.
_relative_path = st.text(max_size=64)


# --- Property 4: Suggested patch name slug generation ---
# Feature: collect-all-patches, Property 4: For any workflow identifier string
# (matching [a-zA-Z0-9_-]+) and any relative file path string, the suggested patch
# name SHALL: (a) match the pattern ^[a-zA-Z0-9_-]+$, (b) not contain consecutive
# underscores, (c) begin with the workflow identifier prefix followed by an
# underscore.

_VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class TestSuggestedPatchNameSlug:
    """**Validates: Requirements 5.4**"""

    @given(
        workflow_identifier=_workflow_identifier,
        relative_path=_relative_path,
    )
    @settings(max_examples=100)
    def test_suggested_name_is_valid_slug(
        self,
        workflow_identifier: str,
        relative_path: str,
    ) -> None:
        """Suggested names are valid slugs with the required prefix.

        (a) match ^[a-zA-Z0-9_-]+$, (b) no consecutive underscores, and
        (c) begin with ``<workflow_identifier>_``.

        Feature: collect-all-patches, Property 4: Suggested patch name slug generation
        """
        name = suggest_patch_name(workflow_identifier, relative_path)

        # (a) The name matches the allowed patch-name character set.
        assert _VALID_NAME_PATTERN.match(name), (
            f"suggested name {name!r} does not match ^[a-zA-Z0-9_-]+$"
        )

        # (b) No consecutive underscores.
        assert "__" not in name, (
            f"suggested name {name!r} contains consecutive underscores"
        )

        # (c) Begins with the workflow identifier prefix followed by "_".
        assert name.startswith(f"{workflow_identifier}_"), (
            f"suggested name {name!r} does not begin with "
            f"{workflow_identifier + '_'!r}"
        )


# --- Property 6: Patch name validation ---
# Feature: collect-all-patches, Property 6: Patch name validation
# validate_patch_name_available(name, existing_names) returns True iff `name` is
# a non-empty string matching [a-zA-Z0-9_-]+ AND is not already present in
# `existing_names`; for every other input it prints an error and returns False.

# Names drawn only from the allowed patch-name character set. min_size=1 keeps
# them non-empty so, on their own, they satisfy the format predicate.
_valid_name = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=32,
)

# Arbitrary Unicode strings (including the empty string and strings containing
# characters outside the allowed set) so we exercise the rejection paths too.
_arbitrary_name = st.text(max_size=32)

# A candidate name is drawn from either pool with equal weight, so the property
# sees valid names, invalid names, and the empty string.
_candidate_name = st.one_of(_valid_name, _arbitrary_name)

# A registry of already-registered names.
_existing_names = st.sets(_valid_name, max_size=8)


def _is_available(name: str, existing_names: "set[str]") -> bool:
    """Reference predicate: valid non-empty slug not already registered."""
    return bool(_VALID_NAME_PATTERN.match(name)) and name not in existing_names


class TestPatchNameValidation:
    """**Validates: Requirements 5.4, 5.5**"""

    @given(
        name=_candidate_name,
        existing_names=_existing_names,
    )
    @settings(max_examples=100)
    def test_validation_matches_predicate(
        self,
        name: str,
        existing_names: "set[str]",
    ) -> None:
        """The boolean result equals the valid-and-available predicate.

        Accepts only non-empty ``[a-zA-Z0-9_-]+`` names not already in the
        registry; rejects everything else.

        Feature: collect-all-patches, Property 6: Patch name validation
        """
        from nf_ica_cli.patch_prompter import validate_patch_name_available

        result = validate_patch_name_available(name, existing_names)
        expected = _is_available(name, existing_names)

        assert result == expected, (
            f"validate_patch_name_available({name!r}, {existing_names!r}) "
            f"returned {result}, expected {expected}"
        )

    @given(name=_valid_name)
    @settings(max_examples=100)
    def test_registered_name_is_rejected(self, name: str) -> None:
        """A valid name already in the registry is always rejected.

        Feature: collect-all-patches, Property 6: Patch name validation
        """
        from nf_ica_cli.patch_prompter import validate_patch_name_available

        # The name is valid in format but present in the registry, so it must
        # be reported as unavailable regardless of its exact value.
        assert validate_patch_name_available(name, {name}) is False
