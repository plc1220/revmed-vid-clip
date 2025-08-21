import os
import google
from google.cloud import storage
from typing import List, Tuple
import datetime
import logging

# --- Centralized GCS Client Initialization ---
_storage_client = None


def get_storage_client() -> storage.Client:
    """
    Initializes and returns a singleton GCS storage client.
    It uses credentials from the environment variable GOOGLE_APPLICATION_CREDENTIALS.
    """
    global _storage_client
    if _storage_client is None:
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        try:
            if credentials_path:
                _storage_client = storage.Client.from_service_account_json(credentials_path)
            else:
                _storage_client = storage.Client()
        except Exception as e:
            raise IOError(f"Failed to initialize GCS client: {e}") from e

    return _storage_client


# --- GCS Helper Functions ---


def ensure_gcs_folder_exists(bucket_name: str, folder_name: str) -> Tuple[bool, str]:
    """
    Ensures a GCS 'folder' exists by creating a .placeholder file if it's empty.
    """
    if not folder_name.endswith("/"):
        folder_name += "/"
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=folder_name, max_results=1))
        if not blobs:
            placeholder_blob_name = f"{folder_name}.gcs_folder_placeholder"
            blob = bucket.blob(placeholder_blob_name)
            blob.upload_from_string("", content_type="text/plain")
            logging.info(f"Created placeholder for GCS folder: gs://{bucket_name}/{folder_name}")
        return True, ""
    except Exception as e:
        error_msg = f"Error ensuring GCS folder gs://{bucket_name}/{folder_name} exists: {e}"
        logging.error(error_msg)
        return False, error_msg


def list_gcs_files(bucket_name: str, prefix: str = "", allowed_extensions: List[str] = None) -> Tuple[List[str], str]:
    """
    Lists files in a GCS bucket with a given prefix and optional extension filtering.
    """
    files = []
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    try:
        storage_client = get_storage_client()
    except IOError as e:
        return [], str(e)

    try:
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            return [], f"Bucket '{bucket_name}' does not exist or you don't have access."

        folder_exists, folder_error = ensure_gcs_folder_exists(bucket_name, prefix)
        if not folder_exists:
            return [], folder_error

        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            if blob.name == f"{prefix}.gcs_folder_placeholder" or blob.name.endswith("/"):
                continue

            if allowed_extensions:
                if any(blob.name.lower().endswith(ext) for ext in allowed_extensions):
                    files.append(blob.name)
            else:
                files.append(blob.name)

        display_location = f"folder '{prefix}' in bucket '{bucket_name}'" if prefix else f"bucket '{bucket_name}'"
        if not files:
            return [], f"No files found in {display_location}."

        return sorted(files), ""
    except Exception as e:
        logging.error(f"GCS LISTING DEBUG: An exception occurred in list_gcs_files for bucket='{bucket_name}' and prefix='{prefix}'.")
        logging.error(f"GCS LISTING DEBUG: Exception type: {type(e).__name__}")
        logging.error(f"GCS LISTING DEBUG: Exception details: {e}", exc_info=True)
        error_message = f"Error listing GCS files from gs://{bucket_name}/{prefix}: {e}"
        logging.error(f"GCS Error: {error_message}")
        return [], error_message


def download_gcs_blob(bucket_name: str, source_blob_name: str, destination_file_name: str) -> Tuple[bool, str]:
    """
    Downloads a blob from the bucket to a local file.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)

        destination_dir = os.path.dirname(destination_file_name)
        if destination_dir:
            os.makedirs(destination_dir, exist_ok=True)

        blob.download_to_filename(destination_file_name)
        return True, ""
    except Exception as e:
        error_msg = f"Error downloading GCS blob gs://{bucket_name}/{source_blob_name} to {destination_file_name}: {e}"
        logging.error(error_msg)
        return False, error_msg


def upload_gcs_blob(bucket_name: str, source_file_name: str, destination_blob_name: str) -> Tuple[bool, str]:
    """
    Uploads a file to the bucket.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        return True, ""
    except Exception as e:
        error_msg = f"Error uploading {source_file_name} to GCS blob gs://{bucket_name}/{destination_blob_name}: {e}"
        logging.error(error_msg)
        return False, error_msg


def delete_gcs_blob(bucket_name: str, blob_name: str) -> Tuple[bool, str]:
    """
    Deletes a blob from the bucket.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        if not blob.exists():
            return False, f"Blob gs://{bucket_name}/{blob_name} not found."

        blob.delete()
        return True, ""
    except Exception as e:
        error_msg = f"Error deleting GCS blob gs://{bucket_name}/{blob_name}: {e}"
        logging.error(error_msg)
        return False, error_msg


def delete_gcs_blobs_batch(bucket_name: str, blob_names: List[str]) -> Tuple[bool, str]:
    """
    Deletes multiple blobs from the bucket in a single batch request.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)

        with storage_client.batch():
            for blob_name in blob_names:
                blob = bucket.blob(blob_name)
                if blob.exists():
                    blob.delete()
                    logging.info(f"Successfully deleted blob gs://{bucket_name}/{blob_name} in batch.")
                else:
                    logging.warning(f"Blob gs://{bucket_name}/{blob_name} not found, skipping deletion.")
        return True, ""
    except Exception as e:
        error_msg = f"Error during batch deletion from GCS bucket gs://{bucket_name}/: {e}"
        logging.error(error_msg)
        return False, error_msg


def generate_signed_url(
    bucket_name: str, blob_name: str, method: str = "GET", content_type: str = None
) -> Tuple[str, str]:
    """
    Generates a signed URL for a GCS blob for GET (download) or PUT (upload).
    """
    try:
        # Use the centralized client which should be initialized with a service account
        credentials, project_id = google.auth.default()
        credentials.refresh(google.auth.transport.requests.Request())
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # URL is valid for 1 hour
        expiration_time = datetime.timedelta(hours=1)

        # Generate the signed URL
        # The client's credentials (from GOOGLE_APPLICATION_CREDENTIALS) will be used automatically.
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=expiration_time,
            method=method,
            content_type=content_type,
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
        return signed_url, ""
    except Exception as e:
        error_msg = f"Error generating signed URL for gs://{bucket_name}/{blob_name} with method {method}: {e}"
        logging.error(error_msg, exc_info=True)
        return "", error_msg


def list_workspaces(bucket_name: str) -> Tuple[List[str], str]:
    """
    Lists top-level 'folders' in a GCS bucket, which represent workspaces.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            return [], f"Bucket '{bucket_name}' does not exist or you don't have access."

        # Use a delimiter to find top-level "directories"
        iterator = bucket.list_blobs(delimiter="/")
        # The prefixes property of the iterator's pages contains the "folder" names
        workspaces = [prefix for page in iterator.pages for prefix in page.prefixes]

        # Clean up the names (remove trailing slash)
        workspaces = [w.strip("/") for w in workspaces]

        return sorted(workspaces), ""
    except Exception as e:
        error_message = f"Error listing workspaces in gs://{bucket_name}/: {e}"
        logging.error(f"GCS Error: {error_message}")
        return [], error_message


def create_workspace(bucket_name: str, workspace_name: str) -> Tuple[bool, str]:
    """
    Creates a new workspace by creating its required sub-folders in GCS.
    """
    if not workspace_name:
        return False, "Workspace name cannot be empty."

    # Define the folder structure for a new workspace
    required_folders = [
        f"{workspace_name}/",
        f"{workspace_name}/uploads/",
        f"{workspace_name}/segments/",
        f"{workspace_name}/metadata/",
        f"{workspace_name}/clips/",
    ]

    try:
        for folder in required_folders:
            success, error = ensure_gcs_folder_exists(bucket_name, folder)
            if not success:
                # If one folder fails, stop and return the error
                return False, f"Failed to create folder '{folder}': {error}"

        return True, f"Workspace '{workspace_name}' created successfully."
    except Exception as e:
        error_msg = f"An unexpected error occurred while creating workspace '{workspace_name}': {e}"
        logging.error(error_msg)
        return False, error_msg
