"""Unit tests for nf_ica_cli.pipeline_exporter module.

Covers ``export_pipeline_source`` for the collect-all-patches subcommand:
missing-token fail-fast, ICA authentication/authorization failure,
pipeline-not-found, per-file download failure with temp-dir cleanup, and a
successful download that preserves the pipeline source structure.

The wrapica download call is not available in the test environment, so
``download_pipeline_to_directory`` is mocked at its import site in
``nf_ica_cli.pipeline_exporter``. The libica exceptions are real exception
classes constructed with a status/reason so the exporter's status-based
branching is exercised end-to-end.

Validates: Requirements 3.2, 3.3, 3.4, 3.5, 7.2, 7.3
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from libica.openapi.v3 import ApiException
from libica.openapi.v3.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)

from nf_ica_cli.pipeline_exporter import export_pipeline_source

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PIPELINE_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def output_dir(tmp_path):
    """A pre-created output directory the exporter downloads into."""
    target = tmp_path / "pipeline_export"
    target.mkdir()
    return target


class TestMissingTokenFailFast:
    """No ICAV2_ACCESS_TOKEN -> fail before any ICA API call.

    Validates: Requirements 3.2, 7.2.
    """

    def test_unset_token_raises_before_api_call(self, output_dir, monkeypatch):
        monkeypatch.delenv("ICAV2_ACCESS_TOKEN", raising=False)

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory"
        ) as mock_download:
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert "[AUTH]" in error_msg
        assert "ICAV2_ACCESS_TOKEN" in error_msg
        # Fail-fast: the download must never be attempted.
        mock_download.assert_not_called()

    def test_empty_token_raises_before_api_call(self, output_dir, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory"
        ) as mock_download:
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        assert "[AUTH]" in str(exc_info.value)
        mock_download.assert_not_called()


class TestAuthFailure:
    """Auth/authorization failures from wrapica surface as AUTH errors.

    Validates: Requirements 3.3, 7.3.
    """

    def test_unauthorized_exception_raises_auth_error(self, output_dir, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=UnauthorizedException(status=401, reason="unauth"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert "[AUTH]" in error_msg
        assert PIPELINE_ID in error_msg

    def test_forbidden_exception_raises_auth_error(self, output_dir, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=ForbiddenException(status=403, reason="forbidden"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        assert "[AUTH]" in str(exc_info.value)

    def test_plain_api_exception_401_raises_auth_error(self, output_dir, monkeypatch):
        """An auth status arriving as a plain ApiException is still AUTH."""
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=ApiException(status=401, reason="unauth"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert "[AUTH]" in error_msg
        # An auth failure must not delete the output directory.
        assert output_dir.exists()


class TestPipelineNotFound:
    """A missing pipeline surfaces with project and pipeline context.

    Validates: Requirements 3.4.
    """

    def test_not_found_exception_includes_ids(self, output_dir, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=NotFoundException(status=404, reason="missing"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert PIPELINE_ID in error_msg
        assert PROJECT_ID in error_msg
        # A not-found error must not delete the output directory.
        assert output_dir.exists()

    def test_plain_api_exception_404_includes_ids(self, output_dir, monkeypatch):
        """A 404 arriving as a plain ApiException is still not-found."""
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=ApiException(status=404, reason="missing"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert PIPELINE_ID in error_msg
        assert PROJECT_ID in error_msg
        assert output_dir.exists()


class TestPerFileDownloadFailure:
    """A generic ApiException during download is a per-file failure.

    The partially-populated output directory is removed before the error is
    raised, and the error identifies the pipeline and project.

    Validates: Requirements 3.5.
    """

    def test_download_failure_removes_output_dir(self, output_dir, monkeypatch):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        # Simulate a partially-populated directory from an interrupted download.
        (output_dir / "main.nf").write_text("partial\n")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=ApiException(status=500, reason="server error"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        error_msg = str(exc_info.value)
        assert PIPELINE_ID in error_msg
        assert PROJECT_ID in error_msg
        # The partially-populated directory is cleaned up on download failure.
        assert not output_dir.exists()


class TestSuccessfulDownload:
    """A successful export calls wrapica with the right args and preserves
    the downloaded structure.

    Validates: Requirements 3.2 (token present), 7.1.
    """

    def test_successful_download_calls_wrapica_and_preserves_structure(
        self, output_dir, monkeypatch
    ):
        monkeypatch.setenv("ICAV2_ACCESS_TOKEN", "a-token")

        def fake_download(pipeline_id, output_directory):
            # wrapica writes files preserving relative structure.
            out = Path(output_directory)
            (out / "main.nf").write_text("workflow {}\n")
            conf = out / "conf"
            conf.mkdir(parents=True, exist_ok=True)
            (conf / "ica.config").write_text("params {}\n")

        with patch(
            "nf_ica_cli.pipeline_exporter.download_pipeline_to_directory",
            side_effect=fake_download,
        ) as mock_download:
            result = export_pipeline_source(PROJECT_ID, PIPELINE_ID, output_dir)

        # Returns None on success.
        assert result is None

        # wrapica is called with the pipeline id and output directory.
        mock_download.assert_called_once_with(
            pipeline_id=PIPELINE_ID,
            output_directory=output_dir,
        )

        # The downloaded structure is preserved on disk.
        assert (output_dir / "main.nf").read_text() == "workflow {}\n"
        assert (output_dir / "conf" / "ica.config").read_text() == "params {}\n"
