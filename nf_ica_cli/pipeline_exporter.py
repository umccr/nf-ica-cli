"""ICA pipeline source exporter for nf-ica CLI.

Downloads the source files of an ICA pipeline into a local directory via the
wrapica library, preserving the relative directory structure of the pipeline
source. Encapsulates the wrapica dependency and the authentication check so the
handler stays testable with simple mocks.

Authentication uses the ``ICAV2_ACCESS_TOKEN`` environment variable, which
wrapica reads as the Bearer token for all ICA API requests.
"""

import os
import shutil
from pathlib import Path

from libica.openapi.v3 import ApiException
from libica.openapi.v3.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from wrapica.pipelines import download_pipeline_to_directory


def export_pipeline_source(
    project_id: str,
    pipeline_id: str,
    output_dir: Path,
) -> None:
    """Download all pipeline source files from ICA into ``output_dir``.

    Reads the ``ICAV2_ACCESS_TOKEN`` environment variable and requires it to be
    set and non-empty before any ICA API call is attempted. All pipeline files
    are downloaded via ``wrapica.pipelines.download_pipeline_to_directory``,
    which lists the pipeline files and downloads each one preserving its
    relative path within ``output_dir``.

    Args:
        project_id: The ICA project UUID containing the pipeline. Used for
            error context (the download is keyed on the pipeline UUID).
        pipeline_id: The ICA pipeline UUID to export source from.
        output_dir: The local directory to download the pipeline files into.

    Raises:
        RuntimeError: If the ``ICAV2_ACCESS_TOKEN`` environment variable is
            unset or empty, if authentication/authorization fails, if the
            pipeline is not found in the project, or if downloading any pipeline
            file fails. In the download-failure case the ``output_dir`` is
            removed before the error is raised.
    """
    # Fail fast if the access token is missing before any ICA API call.
    access_token = os.environ.get("ICAV2_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError(
            "Error: [AUTH] ICAV2_ACCESS_TOKEN environment variable is not set "
            "or is empty. Set ICAV2_ACCESS_TOKEN to a valid ICA access token "
            "before exporting pipeline source."
        )

    try:
        download_pipeline_to_directory(
            pipeline_id=pipeline_id,
            output_directory=output_dir,
        )
    except (UnauthorizedException, ForbiddenException) as e:
        # Authentication or authorization failure — halt immediately.
        raise RuntimeError(
            f"Error: [AUTH] ICA authentication failed while exporting pipeline "
            f"'{pipeline_id}': the access token may be expired or invalid. {e}"
        ) from e
    except NotFoundException as e:
        # Pipeline (or one of its files) could not be found.
        raise RuntimeError(
            f"Error: [ICA API] Pipeline '{pipeline_id}' was not found in "
            f"project '{project_id}'. Verify the project ID and pipeline ID "
            f"are correct. {e}"
        ) from e
    except ApiException as e:
        # A file download failed after the operation started. Distinguish an
        # auth/not-found status that arrives as a plain ApiException, otherwise
        # treat it as a per-file download failure and remove the temp dir.
        status = getattr(e, "status", None)
        if status in (401, 403):
            raise RuntimeError(
                f"Error: [AUTH] ICA authentication failed while exporting "
                f"pipeline '{pipeline_id}': the access token may be expired or "
                f"invalid. {e}"
            ) from e
        if status == 404:
            raise RuntimeError(
                f"Error: [ICA API] Pipeline '{pipeline_id}' was not found in "
                f"project '{project_id}'. Verify the project ID and pipeline "
                f"ID are correct. {e}"
            ) from e
        # Per-file download failure: clean up the partially-populated directory.
        shutil.rmtree(output_dir, ignore_errors=True)
        raise RuntimeError(
            f"Error: [ICA API] Failed to download a source file for pipeline "
            f"'{pipeline_id}' in project '{project_id}'. The temporary export "
            f"directory has been removed. {e}"
        ) from e
