import os
import uuid
import shutil
import logging
import subprocess
import face_recognition
import cv2
import numpy as np
import requests
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# Add backend directory to sys.path to import gcs_service
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import gcs_service

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Temporary Storage ---
TEMP_STORAGE_PATH = "./temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

# --- Helper Functions ---
def download_file_from_gcs(gcs_bucket: str, gcs_blob_name: str, local_path: str):
    """Downloads a file from a GCS signed URL to a local path."""
    try:
        signed_url, error = gcs_service.generate_signed_url(gcs_bucket, gcs_blob_name)
        if error:
            raise Exception(f"Failed to generate signed URL for {gcs_blob_name}: {error}")

        response = requests.get(signed_url, stream=True)
        response.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Successfully downloaded gs://{gcs_bucket}/{gcs_blob_name}")
    except (requests.exceptions.RequestException, Exception) as e:
        raise Exception(f"Failed to download gs://{gcs_bucket}/{gcs_blob_name}: {e}")

def load_known_faces(image_paths: List[str]) -> Tuple[List[np.ndarray], List[str]]:
    """Loads faces from multiple image files."""
    known_encodings = []
    known_names = []
    
    for image_path in image_paths:
        try:
            image = face_recognition.load_image_file(image_path)
            if image.dtype != np.uint8:
                image = image.astype(np.uint8)
            
            face_locations = face_recognition.face_locations(image, model="hog")
            
            if face_locations:
                encodings = face_recognition.face_encodings(
                    image, 
                    known_face_locations=face_locations,
                    num_jitters=0
                )
                
                for encoding in encodings:
                    known_encodings.append(encoding)
                    known_names.append(os.path.basename(image_path))
                    
                logger.info(f"Loaded {len(encodings)} face(s) from {os.path.basename(image_path)}")
            else:
                logger.warning(f"No faces found in {image_path}")
                
        except Exception as e:
            logger.error(f"Error loading faces from {image_path}: {e}")
    
    return known_encodings, known_names

def process_frame_batch(frames_data, known_face_encodings, tolerance):
    """Processes a batch of frames for face recognition."""
    batch_results = {}
    for frame_number, frame in frames_data:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if rgb_frame.dtype != np.uint8:
            rgb_frame = rgb_frame.astype(np.uint8)

        face_locations = face_recognition.face_locations(rgb_frame, model="hog")
        if face_locations:
            frame_face_encodings = face_recognition.face_encodings(
                rgb_frame, 
                known_face_locations=face_locations,
                num_jitters=0
            )
            
            for frame_encoding in frame_face_encodings:
                matches = face_recognition.compare_faces(
                    known_face_encodings, 
                    frame_encoding,
                    tolerance=tolerance
                )
                if True in matches:
                    batch_results[frame_number] = True
                    break
    return batch_results

def find_scenes_with_any_face(
    video_path: str,
    known_face_encodings: List[np.ndarray],
    frame_skip: int = 10,
    tolerance: float = 0.5,
    batch_size: int = 100
) -> bool:
    """Analyzes a video to find if any of the known faces appear."""
    video_capture = cv2.VideoCapture(video_path)
    if not video_capture.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    logger.info(f"Video has {total_frames} total frames. Processing...")
    
    with ThreadPoolExecutor() as executor:
        futures = []
        frames_batch = []
        frame_number = 0
        while True:
            ret, frame = video_capture.read()
            if not ret:
                break
            
            if frame_number % frame_skip == 0:
                frames_batch.append((frame_number, frame))
            
            if len(frames_batch) >= batch_size:
                futures.append(executor.submit(process_frame_batch, frames_batch, known_face_encodings, tolerance))
                frames_batch = []
            
            frame_number += 1

        if frames_batch:
            futures.append(executor.submit(process_frame_batch, frames_batch, known_face_encodings, tolerance))

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:  # If any frame in the batch has a match
                    video_capture.release()
                    logger.info("Found a matching face. Stopping analysis.")
                    return True
            except Exception as e:
                logger.error(f"Error in frame processing future: {e}")

    video_capture.release()
    logger.info("Completed video analysis. No matching faces found.")
    return False

def run_face_recognition_job(job_id: str, gcs_bucket: str, gcs_video_uri: str, gcs_cast_photo_uris: List[str]):
    """
    Main logic for the face recognition job.
    """
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir)
    logger.info(f"[{job_id}] Starting job for video {gcs_video_uri}")

    try:
        # Download video
        local_video_path = os.path.join(job_temp_dir, os.path.basename(gcs_video_uri))
        download_file_from_gcs(gcs_bucket, gcs_video_uri, local_video_path)

        # Download all cast photos
        local_photo_paths = []
        for photo_uri in gcs_cast_photo_uris:
            clean_photo_uri = photo_uri.replace(f"gs://{gcs_bucket}/", "")
            local_photo_path = os.path.join(job_temp_dir, os.path.basename(clean_photo_uri))
            download_file_from_gcs(gcs_bucket, clean_photo_uri, local_photo_path)
            local_photo_paths.append(local_photo_path)
        
        known_encodings, _ = load_known_faces(local_photo_paths)
        if not known_encodings:
            logger.error(f"[{job_id}] No valid faces found in the provided photos. Exiting.")
            return

        face_found = find_scenes_with_any_face(local_video_path, known_encodings)
        
        if not face_found:
            logger.warning(f"[{job_id}] No matching faces were found in the video. The clip will not be copied.")
            return

        # If a face is found, copy the original clip to the refined_clips folder
        workspace = gcs_video_uri.split('/')[0]
        original_filename = os.path.basename(gcs_video_uri)
        gcs_blob_name = f"{workspace}/refined_clips/{original_filename}"

        logger.info(f"[{job_id}] Face found. Copying {gcs_video_uri} to {gcs_blob_name}...")
        
        # Since we already have the file locally, we can just upload it to the new location
        success, error = gcs_service.upload_gcs_blob(gcs_bucket, local_video_path, gcs_blob_name)
        if not success:
            logger.error(f"Failed to copy {original_filename} to refined_clips: {error}")
        else:
            logger.info(f"Successfully copied clip to {gcs_blob_name}")

        logger.info(f"[{job_id}] Job completed successfully.")

    except Exception as e:
        logger.error(f"[{job_id}] An unexpected error occurred: {e}", exc_info=True)
        # In a real-world scenario, you might want to update a job status in a database here
        raise e # Re-raise the exception to mark the Cloud Run Job as failed
    
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

if __name__ == "__main__":
    # Get parameters from environment variables
    try:
        gcs_bucket = os.environ["GCS_BUCKET"]
        gcs_video_uri = os.environ["GCS_VIDEO_URI"]
        # Photo URIs are passed as a comma-separated string
        gcs_cast_photo_uris_str = os.environ["GCS_CAST_PHOTO_URIS"]
        gcs_cast_photo_uris = [uri.strip() for uri in gcs_cast_photo_uris_str.split(',')]
        
        # A unique ID for this job run, can be passed from the caller
        job_id = os.environ.get("JOB_ID", str(uuid.uuid4()))

        run_face_recognition_job(job_id, gcs_bucket, gcs_video_uri, gcs_cast_photo_uris)

    except KeyError as e:
        logger.error(f"Missing required environment variable: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Job failed with an unhandled exception: {e}", exc_info=True)
        sys.exit(1)