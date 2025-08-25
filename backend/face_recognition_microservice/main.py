import os
import uuid
import shutil
import logging
import subprocess
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import face_recognition
import cv2
import numpy as np
import requests
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Pydantic Models ---
class FaceRecognitionRequest(BaseModel):
    gcs_bucket: str
    gcs_video_uri: str
    gcs_cast_photo_uris: List[str]

class Scene(BaseModel):
    start_time: float
    end_time: float

# --- FastAPI App ---
app = FastAPI(
    title="Face Recognition Microservice",
    description="A microservice to find scenes with specific faces in a video.",
    version="1.0.0"
)

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Temporary Storage ---
TEMP_STORAGE_PATH = "./temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

# --- GCS Upload Helper ---
def upload_to_gcs(local_path: str, gcs_bucket: str, gcs_blob_name: str):
    """Uploads a file to GCS via the backend service."""
    workspace, _, filename = gcs_blob_name.rpartition('/')
    with open(local_path, 'rb') as f:
        files = {'video_file': (filename, f, 'video/mp4')}
        response = requests.post(
            f"{os.getenv('BACKEND_URL')}/upload-video/",
            files=files,
            data={"workspace": workspace, "gcs_bucket": gcs_bucket}
        )
        response.raise_for_status()
    logger.info(f"Uploaded {local_path} to gs://{gcs_bucket}/{gcs_blob_name}")

# --- Helper Functions ---
def download_file(url: str, local_path: str):
    """Downloads a file from a URL to a local path."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to download {url}: {e}")

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
) -> List[float]:
    """Analyzes a video to find scenes containing ANY of the known faces (OR logic)."""
    video_capture = cv2.VideoCapture(video_path)
    if not video_capture.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    fps = video_capture.get(cv2.CAP_PROP_FPS)
    total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0:
        fps = 30
        logger.warning(f"Could not determine FPS, using default: {fps}")
    
    logger.info(f"Video has {total_frames} total frames at {fps:.2f} FPS. Processing...")
    match_timestamps = []
    matches_found = 0
    
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

        for i, future in enumerate(as_completed(futures)):
            try:
                result = future.result()
                batch_matches = len(result)
                if batch_matches > 0:
                    matches_found += batch_matches
                    for frame_num in result.keys():
                        match_timestamps.append(frame_num / fps)
                logger.info(f"Processed batch {i+1}/{len(futures)}, found {batch_matches} matching frames. Total matches so far: {matches_found}")
            except Exception as e:
                logger.error(f"Error in frame processing future: {e}")

    video_capture.release()
    logger.info(f"Completed video analysis. Found {matches_found} total matching frames.")
    return sorted(match_timestamps)

def consolidate_timestamps(timestamps: List[float], min_gap: float = 3.0) -> List[Tuple[float, float]]:
    """Groups close timestamps into continuous start/end scenes."""
    if not timestamps:
        return []

    clips = []
    timestamps.sort()
    
    clip_start = timestamps[0]
    last_timestamp = timestamps[0]
    
    for i in range(1, len(timestamps)):
        if timestamps[i] - last_timestamp > min_gap:
            clips.append((clip_start, last_timestamp + 1.0))
            clip_start = timestamps[i]
        last_timestamp = timestamps[i]
    
    clips.append((clip_start, last_timestamp + 1.0))
    
    merged_clips = []
    for start, end in clips:
        if merged_clips and start <= merged_clips[-1][1]:
            merged_clips[-1] = (merged_clips[-1][0], max(merged_clips[-1][1], end))
        else:
            merged_clips.append((start, end))
    
    return merged_clips

# --- API Endpoints ---
@app.post("/process-video/", response_model=List[Scene])
async def process_video(request: FaceRecognitionRequest):
    """
    Downloads a video and cast photos, finds scenes with ANY of the cast members (OR logic).
    """
    job_id = str(uuid.uuid4())
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir)
    logger.info(f"[{job_id}] Starting job for video {request.gcs_video_uri}")

    try:
        # Get signed URL for the video
        signed_url_response = requests.get(
            f"{os.getenv('BACKEND_URL')}/gcs/signed-url",
            params={"gcs_bucket": request.gcs_bucket, "blob_name": request.gcs_video_uri},
        )
        signed_url_response.raise_for_status()
        video_url = signed_url_response.json()["url"]

        # Download video
        local_video_path = os.path.join(job_temp_dir, os.path.basename(request.gcs_video_uri))
        download_file(video_url, local_video_path)

        # Download all cast photos
        local_photo_paths = []
        for photo_uri in request.gcs_cast_photo_uris:
            clean_photo_uri = photo_uri.replace(f"gs://{request.gcs_bucket}/", "")
            signed_url_response = requests.get(
                f"{os.getenv('BACKEND_URL')}/gcs/signed-url",
                params={"gcs_bucket": request.gcs_bucket, "blob_name": clean_photo_uri},
            )
            signed_url_response.raise_for_status()
            photo_url = signed_url_response.json()["url"]
            local_photo_path = os.path.join(job_temp_dir, os.path.basename(clean_photo_uri))
            download_file(photo_url, local_photo_path)
            local_photo_paths.append(local_photo_path)
        
        known_encodings, _ = load_known_faces(local_photo_paths)
        if not known_encodings:
            raise HTTPException(status_code=400, detail="No valid faces found in the provided photos.")

        timestamps = find_scenes_with_any_face(local_video_path, known_encodings)
        scenes = consolidate_timestamps(timestamps)
        
        if not scenes:
            logger.warning(f"[{job_id}] No scenes with matching faces were found. No clips will be generated.")
            return []

        scene_objects = [Scene(start_time=round(s, 2), end_time=round(e, 2)) for s, e in scenes]
        
        # After processing, upload the refined clips
        workspace = request.gcs_video_uri.split('/')[0]
        video_basename = os.path.splitext(os.path.basename(request.gcs_video_uri))[0]
        CLIP_FILENAME_TEMPLATE = "{basename}_refined_clip_{index}.mp4"
        for i, scene in enumerate(scene_objects):
            clip_filename = CLIP_FILENAME_TEMPLATE.format(basename=video_basename, index=i+1)
            local_clip_path = os.path.join(job_temp_dir, clip_filename)
            
            # Use ffmpeg to cut the clip, re-encoding to avoid issues
            try:
                # Use subprocess.run to wait for ffmpeg to complete
                ffmpeg_command = [
                    "ffmpeg",
                    "-i", local_video_path,
                    "-ss", str(scene.start_time),
                    "-to", str(scene.end_time),
                    "-y",
                    local_clip_path
                ]
                # Redirect stdout/stderr to DEVNULL to avoid consuming memory
                result = subprocess.run(
                    ffmpeg_command,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE
                )
                logger.info(f"Successfully created clip: {local_clip_path}")
            except subprocess.CalledProcessError as e:
                # Decode stderr from bytes to string for logging
                error_message = e.stderr.decode('utf-8') if e.stderr else 'No error output'
                logger.error(f"ffmpeg failed for {local_clip_path}: {error_message}")
                # Decide if you want to skip this clip or raise an exception
                continue  # Skip to the next scene if a clip fails

            if not os.path.exists(local_clip_path):
                logger.error(f"Clip file was not created: {local_clip_path}")
                continue

            gcs_blob_name = f"{workspace}/refined_clips/{clip_filename}"
            upload_to_gcs(local_clip_path, request.gcs_bucket, gcs_blob_name)

        return scene_objects
    
    except Exception as e:
        logger.error(f"[{job_id}] An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

# --- Health Check ---
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "face-recognition"}