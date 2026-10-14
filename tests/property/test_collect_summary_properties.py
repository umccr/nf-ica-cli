"""Property-based tests for the collect-all-patches summary output.

Tests correctness properties from the collect-all-patches design document
using Hypothesis.

The design's testing strategy maps Property 7 to the handler's summary logic,
factored into the importable helper
:func:`nf_ica_cli.handlers.collect_all_patches._print_summary`. That helper
takes a list of :class:`~nf_ica_cli.patch_registrar.CollectedPatch` results and
writes to stdout:

* one tab-separated ``name<TAB>patches/<md5sum>.txt`` line per registered
  (non-skipped) patch, then
* a final ``Summary: <new> new, <reused> reused, <skipped> skipped.`` line.

**Validates: Requirements 6.1, 6.2**
"""

import io
import re
from contextlib import redirect_stdout

from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.handlers.collect_all_patches import _print_summary
from nf_ica_cli.patch_registrar import CollectedPatch


# --- Strategies ---

# MD5 hex digests are 32 lowercase hex characters. The exact value is
# irrelevant to the summary logic, so we generate arbitrary hex strings of the
# right shape to exercise the ``patches/<md5>.txt`` path formatting.
_md5sum = st.text(alphabet="0123456789abcdef", min_size=32, max_size=32)

# Patch names come from the [a-zA-Z0-9_-] character set (see validators). They
# must not contain a tab, which is the field separator we assert against.
_name = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=40,
)

# Relative paths are recorded on the CollectedPatch but not emitted by the
# summary (the emitted path is the content-addressed patches/<md5>.txt), so a
# simple non-empty text strategy suffices.
_relative_path = st.text(min_size=1, max_size=40)

# Descriptions are likewise not emitted; keep them arbitrary but bounded.
_description = st.text(max_size=40)


def _new_patch() -> st.SearchStrategy[CollectedPatch]:
    """A registered, newly stored patch (is_new=True, was_skipped=False)."""
    return st.builds(
        CollectedPatch,
        name=_name,
        description=_description,
        relative_path=_relative_path,
        md5sum=_md5sum,
        is_new=st.just(True),
        was_skipped=st.just(False),
    )


def _reused_patch() -> st.SearchStrategy[CollectedPatch]:
    """A registered, content-reused patch (is_new=False, was_skipped=False)."""
    return st.builds(
        CollectedPatch,
        name=_name,
        description=_description,
        relative_path=_relative_path,
        md5sum=_md5sum,
        is_new=st.just(False),
        was_skipped=st.just(False),
    )


def _skipped_patch() -> st.SearchStrategy[CollectedPatch]:
    """A skipped patch (was_skipped=True); is_new is irrelevant."""
    return st.builds(
        CollectedPatch,
        name=st.just(""),
        description=st.just(""),
        relative_path=_relative_path,
        md5sum=_md5sum,
        is_new=st.booleans(),
        was_skipped=st.just(True),
    )


# A list mixing the three categories in arbitrary order and quantity.
_collected_patches = st.lists(
    st.one_of(_new_patch(), _reused_patch(), _skipped_patch()),
    min_size=0,
    max_size=30,
)


# The final summary line, from which we recover the three reported counts.
_SUMMARY_RE = re.compile(
    r"^Summary: (\d+) new, (\d+) reused, (\d+) skipped\.$"
)


# --- Property 7: Summary output correctness ---
# Feature: collect-all-patches, Property 7: For any non-empty list of
# CollectedPatch results (including skipped), the summary output contains exactly
# one tab-separated line per registered (non-skipped) patch, and the final line's
# integer counts satisfy new_count + reused_count + skipped_count == total diffs
# processed.


class TestSummaryOutputCorrectness:
    """**Validates: Requirements 6.1, 6.2**"""

    @given(results=_collected_patches)
    @settings(max_examples=100)
    def test_summary_output_correctness(self, results) -> None:
        """Summary emits one line per registered patch and consistent counts.

        Feature: collect-all-patches, Property 7: Summary output correctness
        """
        # Capture stdout with an in-test StringIO rather than a function-scoped
        # fixture, which Hypothesis will not reset between generated examples.
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _print_summary(results)

        out = buffer.getvalue()
        lines = out.splitlines()
        assert lines, "summary must always emit at least the counts line"

        # The final line is the counts line; everything before it is a
        # tab-separated per-patch line.
        summary_line = lines[-1]
        patch_lines = lines[:-1]

        # (6.1) Exactly one tab-separated line per registered (non-skipped)
        # patch, in input order.
        registered = [r for r in results if not r.was_skipped]
        assert len(patch_lines) == len(registered)

        for line, patch in zip(patch_lines, registered):
            assert "\t" in line
            name, _tab, path = line.partition("\t")
            assert name == patch.name
            assert path == f"patches/{patch.md5sum}.txt"

        # (6.2) The final line reports integer counts.
        match = _SUMMARY_RE.match(summary_line)
        assert match is not None, f"unexpected summary line: {summary_line!r}"
        new_count = int(match.group(1))
        reused_count = int(match.group(2))
        skipped_count = int(match.group(3))

        # The three counts partition the results: their sum equals the total
        # number of diffs processed.
        assert new_count + reused_count + skipped_count == len(results)

        # Each count matches its category.
        expected_new = sum(
            1 for r in results if r.is_new and not r.was_skipped
        )
        expected_reused = sum(
            1 for r in results if not r.is_new and not r.was_skipped
        )
        expected_skipped = sum(1 for r in results if r.was_skipped)

        assert new_count == expected_new
        assert reused_count == expected_reused
        assert skipped_count == expected_skipped
