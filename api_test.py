import requests
import os
import time
import uuid
import json
import subprocess
from google.cloud import storage
from google.api_core import exceptions
from dotenv import load_dotenv

load_dotenv()

# 1. Configuration
GCS_BUCKET_NAME = "lc-ccob-test"
# Use a unique prefix for each test run to avoid collisions
TEST_RUN_ID = str(uuid.uuid4())
LOCAL_VIDEO_PATH = "test.mp4" # Use the provided test video
GCS_UPLOAD_PREFIX = f"test_suite/{TEST_RUN_ID}/uploads/"
API_BASE_URL = "http://127.0.0.1:8000"

# Define GCS prefixes based on the test run ID
# This will be dynamically determined after the split job completes.
GCS_METADATA_PREFIX = f"test_suite/{TEST_RUN_ID}/metadata/"
GCS_CLIPS_PREFIX = f"test_suite/{TEST_RUN_ID}/clips/"
GCS_JOINED_PREFIX = f"test_suite/{TEST_RUN_ID}/joined/"

METADATA_PROMPT_TEMPLATE = """
Analyze the video segment '{{source_filename}}' and identify at least one event with a clear start and end time.
The output must be a JSON object.
Describe the visual elements and any action.
The "action_events" array must contain at least one event with a non-zero duration.

Example of a valid event:
{
  "description": "A short clip of a test pattern.",
  "action_events": [
    {"timestamp": "00:00:01 - 00:00:04", "event": "A test pattern is displayed with various colors."}
  ],
  "transcript": ""
}
"""

CLIP_SELECTION_PROMPT_TEMPLATE = """
You are an AI video editor. From the provided metadata, convert the first event in the "action_events" array into a clip selection.
The output must be a valid JSON array containing only the JSON object for the selected clip.
Use the "timestamp" from the event for the "timestamp_start_end" field.
Use the "event" from the event for the "editor_note_clip_rationale" field.
The "source_filename" should be "{{source_filename}}".
Do not add any explanatory text. The output must be only the JSON array.
Example:
[
  {
    "source_filename": "source_video_part_001.mp4",
    "timestamp_start_end": "00:00:00 - 00:00:05",
    "editor_note_clip_rationale": "The screen is black."
  }
]
"""

# --- Helper Functions ---

def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    """Uploads a file to the bucket."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        print(f"✅ File {source_file_name} uploaded to gs://{bucket_name}/{destination_blob_name}.")
        return True
    except Exception as e:
        print(f"❌ Error uploading to GCS: {e}")
        return False

def list_gcs_blobs(bucket_name, prefix):
    """Lists all blobs in a GCS prefix."""
    try:
        storage_client = storage.Client()
        blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
        return [blob for blob in blobs if not blob.name.endswith('/')]
    except Exception as e:
        print(f"❌ Error listing GCS blobs at gs://{bucket_name}/{prefix}: {e}")
        return []

def cleanup_gcs_folder(bucket_name, prefix):
    """Deletes all files in a GCS folder."""
    print(f"\n🧹 Cleaning up GCS folder: gs://{bucket_name}/{prefix}")
    blobs_to_delete = list_gcs_blobs(bucket_name, prefix)
    if not blobs_to_delete:
        print("    No files to clean up.")
        return
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        for blob in blobs_to_delete:
            print(f"    Deleting {blob.name}...")
            blob.delete()
        print("✅ Cleanup complete.")
    except Exception as e:
        print(f"❌ Error during GCS cleanup: {e}")


def call_api(endpoint, payload):
    """Generic function to call an API endpoint and return the job ID."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        job_id = data.get("job_id")
        print(f"✅ Job started for {endpoint} with job_id: {job_id}")
        return job_id
    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling API {endpoint}: {e}")
        if e.response is not None:
            try:
                print(f"    Response: {e.response.json()}")
            except json.JSONDecodeError:
                print(f"    Response: {e.response.text}")
        return None

def check_job_status(job_id):
    """Polls the job status endpoint."""
    url = f"{API_BASE_URL}/jobs/{job_id}"
    while True:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            status = data.get("status")
            details = data.get("details", "")
            print(f"    Polling Job {job_id}: {status} - {details}")

            if status == "completed":
                print(f"✅ Job {job_id} completed successfully.")
                return "completed"
            elif status == "failed":
                print(f"❌ Job {job_id} failed.")
                return "failed"

            time.sleep(10)
        except requests.exceptions.RequestException as e:
            print(f"    Error checking job status: {e}")
            time.sleep(10)
        except KeyboardInterrupt:
            print("\nTest interrupted by user.")
            return "failed"

# --- Main Test Execution ---

def run_full_test():
    """Runs the end-to-end API test."""
    print("🚀 Starting E2E API Test Suite...")
    print(f"   Test Run ID: {TEST_RUN_ID}")
    print(f"   GCS Bucket: {GCS_BUCKET_NAME}")

    # 1. Upload video via API
    print(f"\n1. Uploading test video '{LOCAL_VIDEO_PATH}' via API...")
    gcs_blob_name = None
    with open(LOCAL_VIDEO_PATH, "rb") as f:
        files = {"file": (os.path.basename(LOCAL_VIDEO_PATH), f, "video/mp4")}
        data = {"gcs_bucket": GCS_BUCKET_NAME, "gcs_prefix": GCS_UPLOAD_PREFIX}
        try:
            url = f"{API_BASE_URL}/upload-video/"
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            upload_data = response.json()
            gcs_blob_name = upload_data.get("gcs_blob_name")
            print(f"   ✅ Video uploaded successfully to gs://{GCS_BUCKET_NAME}/{gcs_blob_name}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error uploading video via API: {e}")
            if e.response is not None:
                print(f"      Response: {e.response.text}")
            return "failed"

    if not gcs_blob_name:
        return "failed"

    # 2. Call split-video endpoint
    print("\n2. Starting video split job...")
    split_job_id = call_api("/split-video/", {
        "gcs_bucket": GCS_BUCKET_NAME,
        "gcs_blob_name": gcs_blob_name,
        "segment_duration": 60,
    })
    if not split_job_id or check_job_status(split_job_id) != "completed":
        return "failed"

    # 3. Find the split video segment for the next step
    print("\n3. Finding split video segment...")
    # The split segments are in a prefix derived from the original video's blob name
    gcs_split_prefix = os.path.splitext(gcs_blob_name)[0] + "_segments/"
    split_blobs = list_gcs_blobs(GCS_BUCKET_NAME, gcs_split_prefix)
    if not split_blobs:
        print("❌ Test failed: No video segments found after split job.")
        return "failed"
    first_segment_blob = split_blobs[0]
    print(f"   Found segment: gs://{GCS_BUCKET_NAME}/{first_segment_blob.name}")

    # 4. Call generate-metadata endpoint
    print("\n4. Starting metadata generation job...")
    metadata_job_id = call_api("/generate-metadata/", {
        "gcs_bucket": GCS_BUCKET_NAME,
        "gcs_video_uris": [f"gs://{GCS_BUCKET_NAME}/{first_segment_blob.name}"],
        "prompt_template": METADATA_PROMPT_TEMPLATE,
        "ai_model_name": "gemini-2.5-flash",
        "gcs_output_prefix": GCS_METADATA_PREFIX
    })
    if not metadata_job_id or check_job_status(metadata_job_id) != "completed":
        return "failed"

    # 5. Find the metadata file
    print("\n5. Finding metadata file...")
    metadata_blobs = list_gcs_blobs(GCS_BUCKET_NAME, GCS_METADATA_PREFIX)
    if not metadata_blobs:
        print("❌ Test failed: No metadata file found after metadata job.")
        return "failed"
    metadata_blob = metadata_blobs[0]
    print(f"   Found metadata file: gs://{GCS_BUCKET_NAME}/{metadata_blob.name}")

    # 6. Call generate-clips endpoint
    print("\n6. Starting clip generation job...")
    # The prompt here should guide the AI to select clips from the metadata.
    # We will use a simplified prompt for the test.
    ai_prompt_for_test = f"""
From the provided metadata, please select the first event from the 'action_events' array and create a single clip from it.
Your output must be a valid JSON array containing one object with 'source_filename', 'timestamp_start_end', and 'editor_note_clip_rationale'.
The source_filename should be '{os.path.basename(first_segment_blob.name)}'.

Example of the expected output format:
[
  {{
    "source_filename": "{os.path.basename(first_segment_blob.name)}",
    "timestamp_start_end": "00:00:00 - 00:00:05",
    "editor_note_clip_rationale": "The event description from the metadata."
  }}
]
"""
    clips_job_id = call_api("/generate-clips/", {
        "gcs_bucket": GCS_BUCKET_NAME,
        "metadata_blob_name": metadata_blob.name,
        "ai_prompt": ai_prompt_for_test,
        "ai_model_name": "gemini-2.5-flash", # Using a fast model for the test
        "output_gcs_prefix": GCS_CLIPS_PREFIX
    })
    if not clips_job_id or check_job_status(clips_job_id) != "completed":
        return "failed"

    # 7. Find the generated clips
    print("\n7. Finding generated clips...")
    clip_blobs = list_gcs_blobs(GCS_BUCKET_NAME, GCS_CLIPS_PREFIX)
    if not clip_blobs:
        print("❌ Test failed: No clips found after clip generation job.")
        return "failed"
    clip_blob_names = [blob.name for blob in clip_blobs]
    print(f"   Found {len(clip_blob_names)} clips.")

    # 8. Call join-videos endpoint
    print("\n8. Starting video joining job...")
    join_job_id = call_api("/join-videos/", {
        "gcs_bucket": GCS_BUCKET_NAME,
        "clip_blob_names": clip_blob_names,
        "output_gcs_prefix": GCS_JOINED_PREFIX
    })
    if not join_job_id or check_job_status(join_job_id) != "completed":
        return "failed"

    # 9. Verify final output
    print("\n9. Verifying final joined video...")
    joined_blobs = list_gcs_blobs(GCS_BUCKET_NAME, GCS_JOINED_PREFIX)
    if not joined_blobs:
        print("❌ Test failed: No final joined video found.")
        return "failed"
    print(f"   ✅ Final video created: gs://{GCS_BUCKET_NAME}/{joined_blobs[0].name}")

    return "completed"


if __name__ == "__main__":
    final_status = "failed"
    try:
        # Check for credentials and API key before starting
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            print("❌ FATAL: GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
            exit(1)

        if not os.getenv("GEMINI_API_KEY"):
            print("❌ FATAL: GEMINI_API_KEY environment variable is not set.")
            exit(1)
        
        final_status = run_full_test()
    except Exception as e:
        print(f"\nAn unexpected error occurred during the test run: {e}")
    finally:
        # Clean up local and GCS files
        # No need to remove LOCAL_VIDEO_PATH as it's part of the repo
        cleanup_gcs_folder(GCS_BUCKET_NAME, f"test_suite/{TEST_RUN_ID}/")
        
        if final_status == "completed":
            print("\n🎉🎉🎉 E2E API Test Suite PASSED! 🎉🎉🎉")
        else:
            print("\n🔥🔥🔥 E2E API Test Suite FAILED! 🔥🔥🔥")
