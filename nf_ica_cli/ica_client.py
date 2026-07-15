"""ICA client for nf-ica CLI.

Handles authentication and pipeline operations on Illumina Connected Analytics
via the wrapica library. Uses OIDC-based authentication through AWS STS and
Secrets Manager to obtain ICA JWT tokens.
"""

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import boto3
from wrapica.project_pipelines import (
    ProjectPipeline,
    create_nextflow_pipeline_from_zip,
    list_project_pipelines,
    add_pipeline_file,
    delete_pipeline_file,
    get_project_pipeline_obj,
    update_pipeline_file,
)


@dataclass
class DeploymentTarget:
    """Represents an ICA project to deploy a pipeline to.

    Attributes:
        project_id: The ICA project UUID.
        project_name: Human-readable project name.
        tenant_name: The tenant this project belongs to.
        aws_role_arn: AWS IAM role ARN for OIDC assumption.
        secret_arn: AWS Secrets Manager ARN containing the ICA JWT.
    """

    project_id: str
    project_name: str
    tenant_name: str
    aws_role_arn: str
    secret_arn: str


def authenticate_oidc(aws_role_arn: str, secret_arn: str) -> str:
    """Assume AWS role via OIDC and retrieve ICA JWT from Secrets Manager.

    This function performs the following steps:
    1. Retrieves the OIDC token from the GitHub Actions environment
    2. Assumes the specified AWS IAM role using STS AssumeRoleWithWebIdentity
    3. Uses the assumed role credentials to access Secrets Manager
    4. Retrieves the ICA JWT secret value
    5. Sets the ICAV2_ACCESS_TOKEN environment variable for wrapica

    Args:
        aws_role_arn: The ARN of the AWS IAM role to assume via OIDC.
        secret_arn: The ARN of the AWS Secrets Manager secret containing the ICA JWT.

    Returns:
        The ICA JWT token string.

    Raises:
        RuntimeError: If OIDC token is not available, role assumption fails,
            or secret retrieval fails.
    """
    # Get the OIDC token from the GitHub Actions environment
    token_file = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    token_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")

    if not token_file or not token_url:
        # Fallback: try reading from AWS_WEB_IDENTITY_TOKEN_FILE (standard OIDC)
        web_identity_token_file = os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
        if web_identity_token_file:
            with open(web_identity_token_file) as f:
                web_identity_token = f.read().strip()
        else:
            raise RuntimeError(
                "Error: [AUTH] OIDC token not available. "
                "Ensure this is running in a GitHub Actions environment with "
                "id-token: write permission, or AWS_WEB_IDENTITY_TOKEN_FILE is set."
            )
    else:
        # In GitHub Actions, get token via the request URL
        import urllib.request

        req = urllib.request.Request(
            f"{token_url}&audience=sts.amazonaws.com",
            headers={"Authorization": f"bearer {token_file}"},
        )
        with urllib.request.urlopen(req) as response:
            token_data = json.loads(response.read().decode())
            web_identity_token = token_data["value"]

    # Step 2: Assume AWS role via STS with the OIDC token
    try:
        sts_client = boto3.client("sts")
        assumed_role = sts_client.assume_role_with_web_identity(
            RoleArn=aws_role_arn,
            RoleSessionName="nf-ica-cli-deployment",
            WebIdentityToken=web_identity_token,
        )
    except Exception as e:
        raise RuntimeError(
            f"Error: [AUTH] Failed to assume AWS role '{aws_role_arn}' "
            f"via OIDC: {e}"
        ) from e

    # Step 3: Create a Secrets Manager client with assumed role credentials
    credentials = assumed_role["Credentials"]
    try:
        secrets_client = boto3.client(
            "secretsmanager",
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )
    except Exception as e:
        raise RuntimeError(
            f"Error: [AUTH] Failed to create Secrets Manager client: {e}"
        ) from e

    # Step 4: Retrieve the ICA JWT from Secrets Manager
    try:
        secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
        jwt_token = secret_response["SecretString"]
    except Exception as e:
        raise RuntimeError(
            f"Error: [AUTH] Failed to retrieve ICA JWT from secret "
            f"'{secret_arn}': {e}"
        ) from e

    # Step 5: Set the environment variable for wrapica
    os.environ["ICAV2_ACCESS_TOKEN"] = jwt_token

    return jwt_token


def create_pipeline(
    project_id: str,
    workflow_name: str,
    version: str,
    source_dir: Path,
    nextflow_version: str,
    description: str,
) -> str:
    """Create a new Nextflow pipeline on ICA using wrapica.

    Zips the source directory and uploads it via wrapica's pipeline
    creation API to create a new pipeline in the specified project.

    Args:
        project_id: The ICA project UUID to create the pipeline in.
        workflow_name: The name of the workflow (used as pipeline name prefix).
        version: The version tag of the workflow.
        source_dir: Path to the directory containing the Nextflow pipeline source.
        nextflow_version: The Nextflow version to use on ICA.
        description: Human-readable description for the pipeline.

    Returns:
        The pipeline_id (UUID string) of the newly created pipeline.

    Raises:
        RuntimeError: If pipeline creation fails.
    """
    # Create a zip archive of the source directory
    zip_path = _zip_source_directory(source_dir)

    try:
        pipeline_code = f"{workflow_name}__{version}"

        # Create the pipeline via wrapica
        pipeline = create_nextflow_pipeline_from_zip(
            project_id=project_id,
            pipeline_code=pipeline_code,
            zip_path=zip_path,
            workflow_description=description,
        )

        return pipeline.pipeline.id
    except Exception as e:
        raise RuntimeError(
            f"Error: [ICA API] Failed to create pipeline "
            f"'{workflow_name}' v{version} in project '{project_id}': {e}"
        ) from e
    finally:
        # Clean up the temporary zip file
        if zip_path.exists():
            zip_path.unlink()


def update_existing_pipeline(
    project_id: str,
    pipeline_id: str,
    source_dir: Path,
    nextflow_version: str,
    description: str,
) -> None:
    """Update an existing pipeline on ICA using wrapica.

    Updates the pipeline by iterating through source files and using
    wrapica's file management functions (add/update) to synchronize
    the pipeline content.

    Args:
        project_id: The ICA project UUID containing the pipeline.
        pipeline_id: The UUID of the pipeline to update.
        source_dir: Path to the directory containing the updated Nextflow source.
        nextflow_version: The Nextflow version to use on ICA.
        description: Updated description for the pipeline.

    Raises:
        RuntimeError: If pipeline update fails.
    """
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Source directory not found: '{source_dir}'."
        )

    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Source path is not a directory: '{source_dir}'."
        )

    try:
        # Get the existing pipeline to access its files
        pipeline_obj = get_project_pipeline_obj(
            project_id=project_id,
            pipeline_id=pipeline_id,
        )

        # Add/update all files from the source directory
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                relative_path = file_path.relative_to(source_dir)
                add_pipeline_file(
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    file_path=file_path,
                    relative_path=relative_path,
                )
    except Exception as e:
        raise RuntimeError(
            f"Error: [ICA API] Failed to update pipeline '{pipeline_id}' "
            f"in project '{project_id}': {e}"
        ) from e


def find_existing_pipeline(
    project_id: str,
    workflow_name: str,
    version: str,
) -> Optional[str]:
    """Check if a pipeline already exists for this workflow/version in the project.

    Searches the project's pipelines for one matching the naming convention
    `<workflow_name>__<version>`.

    Args:
        project_id: The ICA project UUID to search in.
        workflow_name: The workflow name to match.
        version: The version tag to match.

    Returns:
        The pipeline_id (UUID string) if found, None otherwise.

    Raises:
        RuntimeError: If the API call to list pipelines fails.
    """
    expected_code = f"{workflow_name}__{version}"

    try:
        pipelines: List[ProjectPipeline] = list_project_pipelines(
            project_id=project_id,
        )

        for pipeline in pipelines:
            if pipeline.pipeline.code == expected_code:
                return pipeline.pipeline.id

        return None
    except Exception as e:
        raise RuntimeError(
            f"Error: [ICA API] Failed to search for existing pipeline "
            f"'{expected_code}' in project '{project_id}': {e}"
        ) from e


def _zip_source_directory(source_dir: Path) -> Path:
    """Create a zip archive of the source directory.

    Creates a temporary zip file containing all files from source_dir.
    The caller is responsible for cleaning up the zip file.

    Args:
        source_dir: Path to the directory to zip.

    Returns:
        Path to the created zip file.

    Raises:
        FileNotFoundError: If source_dir does not exist.
        RuntimeError: If zipping fails.
    """
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Source directory not found: '{source_dir}'."
        )

    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"Error: [FILE ACCESS] Source path is not a directory: '{source_dir}'."
        )

    # Create a temporary zip file
    tmp_dir = Path(tempfile.mkdtemp())
    zip_path = tmp_dir / "pipeline_source.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(source_dir.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
                    zf.write(file_path, arcname)
    except Exception as e:
        # Clean up on failure
        if zip_path.exists():
            zip_path.unlink()
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise RuntimeError(
            f"Error: [FILE] Failed to create zip archive from "
            f"'{source_dir}': {e}"
        ) from e

    return zip_path
