"""Property-based tests for nf_ica_cli.validators module.

Tests Properties 4-7 from the design document using Hypothesis.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nf_ica_cli.validators import (
    validate_git_commit_id,
    validate_patch_name,
    validate_release_status,
    validate_context,
)


# --- Strategies ---

# Valid git commit ID: 7-40 chars from [a-f0-9]
valid_git_commit_ids = st.text(
    alphabet="abcdef0123456789",
    min_size=7,
    max_size=40,
)

# Invalid git commit IDs: strings that do NOT match ^[a-f0-9]{7,40}$
# We use several categories of invalidity:
# - Too short (1-6 chars from valid alphabet)
# - Too long (41+ chars from valid alphabet)
# - Correct length but contains invalid chars
# - Empty string
invalid_git_commit_ids_too_short = st.text(
    alphabet="abcdef0123456789",
    min_size=1,
    max_size=6,
)

invalid_git_commit_ids_too_long = st.text(
    alphabet="abcdef0123456789",
    min_size=41,
    max_size=80,
)

invalid_git_commit_ids_bad_chars = st.text(
    alphabet="ghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()",
    min_size=7,
    max_size=40,
).filter(lambda s: len(s) >= 7)

# Valid patch names: non-empty strings from [a-zA-Z0-9_-]
valid_patch_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=100,
)

# Invalid patch names: empty or contain chars outside [a-zA-Z0-9_-]
invalid_patch_names_with_bad_chars = st.text(
    min_size=1,
    max_size=100,
).filter(lambda s: not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in s))

# Context names strategy
context_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=30,
)


# --- Property 4: Git commit ID validation ---
# Feature: nf-ica-cli, Property 4: For any string, the git commit ID validator SHALL accept
# it if and only if it consists of exactly 7 to 40 characters from the set [a-f0-9].


class TestGitCommitIdValidation:
    """**Validates: Requirements 2.7**"""

    @given(commit_id=valid_git_commit_ids)
    @settings(max_examples=100)
    def test_accepts_valid_git_commit_ids(self, commit_id: str) -> None:
        """Valid git commit IDs (7-40 hex chars) are always accepted."""
        # Feature: nf-ica-cli, Property 4: Git commit ID validation
        assert validate_git_commit_id(commit_id) is True

    @given(commit_id=invalid_git_commit_ids_too_short)
    @settings(max_examples=100)
    def test_rejects_too_short_commit_ids(self, commit_id: str) -> None:
        """Commit IDs shorter than 7 chars are always rejected."""
        # Feature: nf-ica-cli, Property 4: Git commit ID validation
        with pytest.raises(ValueError):
            validate_git_commit_id(commit_id)

    @given(commit_id=invalid_git_commit_ids_too_long)
    @settings(max_examples=100)
    def test_rejects_too_long_commit_ids(self, commit_id: str) -> None:
        """Commit IDs longer than 40 chars are always rejected."""
        # Feature: nf-ica-cli, Property 4: Git commit ID validation
        with pytest.raises(ValueError):
            validate_git_commit_id(commit_id)

    @given(commit_id=invalid_git_commit_ids_bad_chars)
    @settings(max_examples=100)
    def test_rejects_commit_ids_with_invalid_chars(self, commit_id: str) -> None:
        """Commit IDs with chars outside [a-f0-9] are always rejected."""
        # Feature: nf-ica-cli, Property 4: Git commit ID validation
        with pytest.raises(ValueError):
            validate_git_commit_id(commit_id)

    @settings(max_examples=100)
    @given(s=st.text(min_size=0, max_size=100))
    def test_biconditional_acceptance(self, s: str) -> None:
        """A string is accepted iff it matches ^[a-f0-9]{7,40}$."""
        # Feature: nf-ica-cli, Property 4: Git commit ID validation
        import re
        should_accept = bool(re.match(r"^[a-f0-9]{7,40}$", s))

        if should_accept:
            assert validate_git_commit_id(s) is True
        else:
            with pytest.raises(ValueError):
                validate_git_commit_id(s)


# --- Property 5: Patch name format validation ---
# Feature: nf-ica-cli, Property 5: For any string, the patch name validator SHALL accept
# it if and only if it is non-empty and consists entirely of characters from the set [a-zA-Z0-9_-].


class TestPatchNameValidation:
    """**Validates: Requirements 8.7**"""

    @given(name=valid_patch_names)
    @settings(max_examples=100)
    def test_accepts_valid_patch_names(self, name: str) -> None:
        """Valid patch names (non-empty, [a-zA-Z0-9_-]) are always accepted."""
        # Feature: nf-ica-cli, Property 5: Patch name format validation
        assert validate_patch_name(name) is True

    @given(name=invalid_patch_names_with_bad_chars)
    @settings(max_examples=100)
    def test_rejects_patch_names_with_invalid_chars(self, name: str) -> None:
        """Patch names with chars outside [a-zA-Z0-9_-] are always rejected."""
        # Feature: nf-ica-cli, Property 5: Patch name format validation
        with pytest.raises(ValueError):
            validate_patch_name(name)

    def test_rejects_empty_patch_name(self) -> None:
        """Empty string is always rejected as a patch name."""
        # Feature: nf-ica-cli, Property 5: Patch name format validation
        with pytest.raises(ValueError):
            validate_patch_name("")

    @settings(max_examples=100)
    @given(s=st.text(min_size=0, max_size=100))
    def test_biconditional_acceptance(self, s: str) -> None:
        """A string is accepted iff it is non-empty and matches ^[a-zA-Z0-9_-]+$."""
        # Feature: nf-ica-cli, Property 5: Patch name format validation
        import re
        should_accept = bool(s) and bool(re.match(r"^[a-zA-Z0-9_-]+$", s))

        if should_accept:
            assert validate_patch_name(s) is True
        else:
            with pytest.raises(ValueError):
                validate_patch_name(s)


# --- Property 6: Release status validation ---
# Feature: nf-ica-cli, Property 6: For any string, the release status validator SHALL accept
# it if and only if it is exactly "DRAFT" or "RELEASED".


class TestReleaseStatusValidation:
    """**Validates: Requirements 3.5, 4.3**"""

    @pytest.mark.parametrize("status", ["DRAFT", "RELEASED"])
    def test_accepts_valid_statuses(self, status: str) -> None:
        """Only 'DRAFT' and 'RELEASED' are accepted."""
        # Feature: nf-ica-cli, Property 6: Release status validation
        assert validate_release_status(status) is True

    @given(s=st.text(min_size=0, max_size=50))
    @settings(max_examples=100)
    def test_rejects_all_other_strings(self, s: str) -> None:
        """Any string other than 'DRAFT' or 'RELEASED' is rejected."""
        # Feature: nf-ica-cli, Property 6: Release status validation
        assume(s not in ("DRAFT", "RELEASED"))
        with pytest.raises(ValueError):
            validate_release_status(s)

    @given(s=st.text(min_size=0, max_size=50))
    @settings(max_examples=100)
    def test_biconditional_acceptance(self, s: str) -> None:
        """A string is accepted iff it is exactly 'DRAFT' or 'RELEASED'."""
        # Feature: nf-ica-cli, Property 6: Release status validation
        should_accept = s in ("DRAFT", "RELEASED")

        if should_accept:
            assert validate_release_status(s) is True
        else:
            with pytest.raises(ValueError):
                validate_release_status(s)


# --- Property 7: Context cross-reference validation ---
# Feature: nf-ica-cli, Property 7: For any context value and a set of defined context names,
# the context validator SHALL reject the value with an error if and only if the value is
# not present in the defined set.


class TestContextValidation:
    """**Validates: Requirements 2.5, 3.7**"""

    @given(
        contexts=st.lists(context_names, min_size=1, max_size=20, unique=True),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_accepts_context_in_defined_set(
        self, contexts: list, data: st.DataObject
    ) -> None:
        """A context value present in the defined set is always accepted."""
        # Feature: nf-ica-cli, Property 7: Context cross-reference validation
        value = data.draw(st.sampled_from(contexts))
        assert validate_context(value, contexts) is True

    @given(
        contexts=st.lists(context_names, min_size=0, max_size=20, unique=True),
        value=context_names,
    )
    @settings(max_examples=100)
    def test_rejects_context_not_in_defined_set(
        self, contexts: list, value: str
    ) -> None:
        """A context value not present in the defined set is always rejected."""
        # Feature: nf-ica-cli, Property 7: Context cross-reference validation
        assume(value not in contexts)
        with pytest.raises(ValueError):
            validate_context(value, contexts)

    @given(
        contexts=st.lists(context_names, min_size=1, max_size=20, unique=True),
        value=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
            min_size=1,
            max_size=30,
        ),
    )
    @settings(max_examples=100)
    def test_biconditional_membership(self, contexts: list, value: str) -> None:
        """A context is accepted iff it is in the defined set; rejected otherwise."""
        # Feature: nf-ica-cli, Property 7: Context cross-reference validation
        if value in contexts:
            assert validate_context(value, contexts) is True
        else:
            with pytest.raises(ValueError):
                validate_context(value, contexts)
