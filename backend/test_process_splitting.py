import os
import uuid
import logging
from dotenv import load_dotenv

from schemas import SplitRequest
from task_service import process_splitting

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_test():
    """
    Runs a standalone test for the process_splitting function.
    """
    # --- Configuration ---
    # Load environment variables from .env file
    load_dotenv()

    # Ensure required environment variables are set
    if not os.getenv("GOOGLE_CLOUD_PROJECT") or not os.getenv("GOOGLE_CLOUD_LOCATION"):
        logging.error("Error: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION environment variables must be set.")
        return

    # --- Mock Request Data ---
    # IMPORTANT: Replace these values with your actual test data
    test_gcs_bucket = "lc-ccob-test"  # Your GCS bucket name
    test_gcs_blob = "Nicholas best video editing folder/uploads/cinta-buat-dara-S1E1.mp4"
    test_workspace = "Nicholas best video editing folder"      # Your workspace folder
    test_segment_duration = 600.0  # Duration of each segment in seconds (e.g., 600s = 10 minutes)

    # Create a mock SplitRequest object
    split_request = SplitRequest(
        gcs_bucket=test_gcs_bucket,
        gcs_blob_name=test_gcs_blob,
        segment_duration=test_segment_duration,
        workspace=test_workspace,
    )

    # Generate a unique job ID for this test run
    job_id = f"test-split-{uuid.uuid4()}"

    logging.info(f"Starting test for job ID: {job_id}")
    logging.info(f"Request details: {split_request}")

    try:
        # Call the function
        process_splitting(job_id, split_request)
        logging.info("process_splitting function executed.")
        logging.info("Check the job_store directory for a file named '{job_id}.json' to see the result.")
        logging.info("You can then use the /jobs/{job_id} endpoint to poll for the final status.")

    except Exception as e:
        logging.error(f"An error occurred during the test: {e}", exc_info=True)

if __name__ == "__main__":
    run_test()