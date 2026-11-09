"""Property-based tests for content-addressed storage via patches.register_patch.

Tests correctness properties from the collect-all-patches design document
using Hypothesis.

The design's testing strategy maps Property 5 to ``patches.register_patch``.
``register_patch`` computes the MD5 of the source file's *bytes* via
``patches.compute_md5`` (byte-level hashing), so the expected digest here is
``hashlib.md5(content).hexdigest()`` over the same raw bytes written to the
source file.

**Validates: Requirements 5.1, 5.2**
"""

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.patches import PatchEntry, register_patch


# --- Strategies ---

# Random byte content for the patch file. Byte content (rather than text)
# matches compute_md5's byte-level hashing and exercises arbitrary payloads.
_patch_content = st.binary(min_size=0, max_size=10000)


# --- Property 5: Content-addressed storage correctness ---
# Feature: collect-all-patches, Property 5: For any patch content, the patch file
# SHALL be stored at patches/<md5>.txt where <md5> equals the MD5 hex digest of the
# content, and if a file with the same MD5 already exists in the registry, no new
# file SHALL be written to disk.


class TestContentAddressedStorage:
    """**Validates: Requirements 5.1, 5.2**"""

    @given(content=_patch_content)
    @settings(max_examples=100)
    def test_stored_at_content_addressed_path(
        self, content: bytes, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """A new patch is written to ``patches/<md5>.txt`` with the correct MD5.

        The stored file path is derived from the MD5 hex digest of the source
        file's bytes, and the stored file's bytes are identical to the source.

        Feature: collect-all-patches, Property 5: Content-addressed storage correctness
        """
        base = tmp_path_factory.mktemp("stored")
        config_repo = base / "config_repo"
        config_repo.mkdir()
        source_file = base / "source.txt"
        source_file.write_bytes(content)

        expected_md5 = hashlib.md5(content).hexdigest()

        entry = register_patch(
            config_repo=config_repo,
            source_file=source_file,
            name="patch-a",
            description="a collected patch",
            existing_patches=[],
        )

        # The returned entry records the content-addressed path and MD5.
        assert entry.md5sum == expected_md5
        assert entry.path == f"patches/{expected_md5}.txt"

        # The file exists on disk at patches/<md5>.txt with the same bytes.
        stored = config_repo / entry.path
        assert stored.is_file(), f"expected stored patch at {stored}"
        assert stored.read_bytes() == content

    @given(content=_patch_content)
    @settings(max_examples=100)
    def test_existing_md5_does_not_write_new_file(
        self, content: bytes, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """When the MD5 already exists in the registry, no new file is written.

        We pre-register an entry with the matching MD5 but do NOT create the
        destination file, then register again. Because the MD5 is already
        known, ``register_patch`` must skip the copy, leaving the destination
        path non-existent on disk.

        Feature: collect-all-patches, Property 5: Content-addressed storage correctness
        """
        base = tmp_path_factory.mktemp("existing")
        config_repo = base / "config_repo"
        config_repo.mkdir()
        source_file = base / "source.txt"
        source_file.write_bytes(content)

        expected_md5 = hashlib.md5(content).hexdigest()
        dest = config_repo / f"patches/{expected_md5}.txt"

        # An existing registry entry with the same MD5 (different name), whose
        # content-addressed file is deliberately absent from disk.
        existing = [
            PatchEntry(
                name="already-registered",
                path=f"patches/{expected_md5}.txt",
                md5sum=expected_md5,
                description="pre-existing duplicate",
            )
        ]
        assert not dest.exists()

        entry = register_patch(
            config_repo=config_repo,
            source_file=source_file,
            name="patch-b",
            description="a duplicate collected patch",
            existing_patches=existing,
        )

        # The path/MD5 still resolve to the content-addressed location...
        assert entry.md5sum == expected_md5
        assert entry.path == f"patches/{expected_md5}.txt"

        # ...but because the MD5 already existed, no new file was written.
        assert not dest.exists(), (
            f"register_patch wrote a new file at {dest} even though the MD5 "
            f"already existed in the registry"
        )
