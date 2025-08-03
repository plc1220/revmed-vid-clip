import os
import shutil
from services.video_service import split_video
from services import gcs_service

# Configuration from api_test.py
GCS_BUCKET_NAME = "lc-ccob-test"

def test_split_video_and_upload_to_gcs():
    """
    Tests the split_video function and then uploads the segments to GCS.
    """
    print("--- Starting test: Split video and Upload to GCS ---")
    
    video_path = "test.mp4"
    segment_duration = 10  # seconds
    output_dir = "test_split_output"

    # --- 1. Local Splitting ---
    print("\n--- Step 1: Splitting video locally ---")
    
    # Clean up previous test runs
    if os.path.exists(output_dir):
        print(f"Removing existing output directory: {output_dir}")
        shutil.rmtree(output_dir)

    print(f"Input video: {video_path}")
    print(f"Segment duration: {segment_duration}s")
    print(f"Output directory: {output_dir}")

    if not os.path.exists(video_path):
        print(f"ERROR: Video file not found at {video_path}")
        print("--- Test Finished ---")
        return

    print("\nCalling video_service.split_video...")
    saved_segments, error_message = split_video(video_path, segment_duration, output_dir)

    print("\n--- Splitting Results ---")
    if error_message:
        print(f"An error occurred during splitting: {error_message}")
    
    if not saved_segments:
        print("No segments were created. Aborting upload.")
        print("--- Test Finished ---")
        return
        
    print(f"Successfully created {len(saved_segments)} local segments.")
    for segment in saved_segments:
        print(f"- {segment}")

    # --- 2. Uploading to GCS ---
    print("\n--- Step 2: Uploading segments to GCS ---")
    print(f"Target GCS Bucket: {GCS_BUCKET_NAME}")
    
    output_prefix = os.path.splitext(os.path.basename(video_path))[0] + "_segments/"
    print(f"Target GCS Prefix: {output_prefix}")

    successful_uploads = 0
    for i, segment_path in enumerate(saved_segments):
        segment_blob_name = os.path.join(output_prefix, os.path.basename(segment_path))
        print(f"  Uploading segment {i+1}/{len(saved_segments)}: {segment_path} to gs://{GCS_BUCKET_NAME}/{segment_blob_name}...")
        
        success, upload_error = gcs_service.upload_gcs_blob(GCS_BUCKET_NAME, segment_path, segment_blob_name)
        
        if success:
            print("    ...Success.")
            successful_uploads += 1
        else:
            print(f"    ...FAILED. Error: {upload_error}")

    print("\n--- Upload Results ---")
    print(f"Successfully uploaded {successful_uploads}/{len(saved_segments)} segments to GCS.")

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    test_split_video_and_upload_to_gcs()
