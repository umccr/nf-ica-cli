"""Property-based tests for content-addressed patch storage determinism.

Tests Property 3 from the design document using Hypothesis.

**Validates: Requirements 8.1, 8.2, 8.3**
"""

import re

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nf_ica_cli.patches import compute_md5


# --- Strategies ---

# Binary content of varying sizes for patch file contents
binary_content = st.binary(min_size=0, max_size=10000)


# --- Property 3: Content-addressed patch storage determinism ---
# Feature: nf-ica-cli, Property 3: For any file contents, the computed storage path
# (`patches/<md5sum>.txt`) is deterministic: identical file contents always produce
# the same MD5 and thus the same storage path, and different file contents produce
# different storage paths (with overwhelmingly high probability given MD5's collision
# resistance for this use case).


class TestPatchStorageDeterminism:
    """**Validates: Requirements 8.1, 8.2, 8.3**"""

    @given(content=binary_content)
    @settings(max_examples=100)
    def test_determinism_same_content_same_md5(
        self, content: bytes, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Same content always produces the same MD5 and same storage path.

        Feature: nf-ica-cli, Property 3: Content-addressed patch storage determinism
        """
        # Write the same content to two different temp files
        base_dir = tmp_path_factory.mktemp("determinism")
        file_a = base_dir / "file_a.txt"
        file_b = base_dir / "file_b.txt"

        file_a.write_bytes(content)
        file_b.write_bytes(content)

        # Compute MD5 for both files
        md5_a = compute_md5(file_a)
        md5_b = compute_md5(file_b)

        # Same content must produce same MD5
        assert md5_a == md5_b

        # Same content must produce same storage path
        path_a = f"patches/{md5_a}.txt"
        path_b = f"patches/{md5_b}.txt"
        assert path_a == path_b

    @given(content_a=binary_content, content_b=binary_content)
    @settings(max_examples=100)
    def test_distinctness_different_content_different_md5(
        self, content_a: bytes, content_b: bytes, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Different content produces different MD5 (with high probability).

        Feature: nf-ica-cli, Property 3: Content-addressed patch storage determinism
        """
        # Only test when contents actually differ
        assume(content_a != content_b)

        base_dir = tmp_path_factory.mktemp("distinctness")
        file_a = base_dir / "file_a.txt"
        file_b = base_dir / "file_b.txt"

        file_a.write_bytes(content_a)
        file_b.write_bytes(content_b)

        md5_a = compute_md5(file_a)
        md5_b = compute_md5(file_b)

        # Different content must produce different MD5 (collision is vanishingly unlikely)
        assert md5_a != md5_b

        # Different MD5s must produce different storage paths
        path_a = f"patches/{md5_a}.txt"
        path_b = f"patches/{md5_b}.txt"
        assert path_a != path_b

    @given(content=binary_content)
    @settings(max_examples=100)
    def test_path_format_matches_pattern(
        self, content: bytes, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Storage path always matches pattern `patches/<32-hex-chars>.txt`.

        Feature: nf-ica-cli, Property 3: Content-addressed patch storage determinism
        """
        base_dir = tmp_path_factory.mktemp("format")
        file_path = base_dir / "patch_file.txt"
        file_path.write_bytes(content)

        md5 = compute_md5(file_path)
        storage_path = f"patches/{md5}.txt"

        # Verify path format: patches/<32 lowercase hex chars>.txt
        assert re.match(r"^patches/[a-f0-9]{32}\.txt$", storage_path), (
            f"Storage path '{storage_path}' does not match expected pattern "
            f"'patches/<32-hex-chars>.txt'"
        )
