import os
from google.cloud import storage
from typing import List, Tuple
import datetime

# --- Centralized GCS Client Initialization ---
_storage_client = None

def get_storage_client() -> storage.Client:
    """
    Initializes and returns a singleton GCS storage client.
    It uses credentials from the environment variable GOOGLE_APPLICATION_CREDENTIALS.
    """
    global _storage_client
    if _storage_client is None:
        try:
            # Explicitly use credentials from the environment variable
            _storage_client = storage.Client.from_service_account_json(
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            )
        except Exception as e:
            print(f"Error initializing GCS client from service account: {e}")
            # Fallback to default client if service account fails
            _storage_client = storage.Client()
    return _storage_client

# --- GCS Helper Functions ---

def ensure_gcs_folder_exists(bucket_name: str, folder_name: str) -> Tuple[bool, str]:
    """
    Ensures a GCS 'folder' exists by creating a .placeholder file if it's empty.
    """
    if not folder_name.endswith('/'):
        folder_name += '/'
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=folder_name, max_results=1))
        if not blobs:
            placeholder_blob_name = f"{folder_name}.gcs_folder_placeholder"
            blob = bucket.blob(placeholder_blob_name)
            blob.upload_from_string("", content_type="text/plain")
            print(f"Created placeholder for GCS folder: gs://{bucket_name}/{folder_name}")
        return True, ""
    except Exception as e:
        error_msg = f"Error ensuring GCS folder gs://{bucket_name}/{folder_name} exists: {e}"
        print(error_msg)
        return False, error_msg

def list_gcs_files(bucket_name: str, prefix: str = "", allowed_extensions: List[str] = None) -> Tuple[List[str], str]:
    """
    Lists files in a GCS bucket with a given prefix and optional extension filtering.
    """
    files = []
    if prefix and not prefix.endswith('/'):
        prefix += '/'

    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            return [], f"Bucket '{bucket_name}' does not exist or you don't have access."

        folder_exists, folder_error = ensure_gcs_folder_exists(bucket_name, prefix)
        if not folder_exists:
            return [], folder_error

        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            if blob.name == f"{prefix}.gcs_folder_placeholder" or blob.name.endswith('/'):
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
        error_message = f"Error listing GCS files from gs://{bucket_name}/{prefix}: {e}"
        print(f"GCS Error: {error_message}")
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
        print(error_msg)
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
        print(error_msg)
        return False, error_msg

def generate_signed_url(bucket_name: str, blob_name: str) -> Tuple[str, str]:
    """
    Generates a signed URL for a GCS blob using the service account.
    """
    try:
        storage_client = get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # URL is valid for 1 hour
        expiration_time = datetime.timedelta(hours=1)
        
        # The client, initialized via get_storage_client, now has the service account key
        url = blob.generate_signed_url(
            version="v4",
            expiration=expiration_time,
            method="GET",
        )
        return url, ""
    except Exception as e:
        error_msg = f"Error generating signed URL for gs://{bucket_name}/{blob_name}: {e}"
        print(error_msg)
        return "", error_msg