import os
import uuid
import shutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import face_recognition
import cv2
import requests
from typing import List, Tuple

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

# --- Temporary Storage ---
TEMP_STORAGE_PATH = "./temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

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

def load_known_face(image_path: str) -> Tuple[List, str]:
    """Loads a single face from an image file."""
    try:
        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)
        if encodings:
            return encodings[0], os.path.basename(image_path)
        return None, ""
    except Exception as e:
        print(f"Error loading face from {image_path}: {e}")
        return None, ""

def find_scenes_with_face(video_path: str, known_face_encoding: List, frame_skip: int = 5) -> List[Tuple[float, float]]:
    """Analyzes a video to find scenes containing a specific face."""
    video_capture = cv2.VideoCapture(video_path)
    fps = video_capture.get(cv2.CAP_PROP_FPS)
    match_timestamps = []
    frame_number = 0

    while video_capture.isOpened():
        ret, frame = video_capture.read()
        if not ret:
            break

        if frame_number % frame_skip == 0:
            rgb_frame = frame[:, :, ::-1]
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces([known_face_encoding], face_encoding)
                if True in matches:
                    timestamp_sec = frame_number / fps
                    match_timestamps.append(timestamp_sec)
                    break
        
        frame_number += 1

    video_capture.release()
    return consolidate_timestamps(match_timestamps)

def consolidate_timestamps(timestamps: List[float], min_gap: float = 3.0) -> List[Tuple[float, float]]:
    """Groups close timestamps into continuous start/end scenes."""
    if not timestamps:
        return []

    clips = []
    timestamps.sort()
    
    clip_start = timestamps[0]
    for i in range(1, len(timestamps)):
        if timestamps[i] - timestamps[i-1] > min_gap:
            clips.append((clip_start, timestamps[i-1]))
            clip_start = timestamps[i]
    
    clips.append((clip_start, timestamps[-1]))
    return clips

# --- API Endpoint ---
@app.post("/process-video/", response_model=List[Scene])
async def process_video(request: FaceRecognitionRequest):
    """
    Downloads a video and cast photos, finds scenes with the cast, and returns the timestamps.
    """
    job_id = str(uuid.uuid4())
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir)

    try:
        # Download video
        video_url = f"https://storage.googleapis.com/{request.gcs_bucket}/{request.gcs_video_uri}"
        local_video_path = os.path.join(job_temp_dir, os.path.basename(request.gcs_video_uri))
        download_file(video_url, local_video_path)

        # Download and load known faces
        known_faces = []
        for photo_uri in request.gcs_cast_photo_uris:
            photo_url = f"https://storage.googleapis.com/{request.gcs_bucket}/{photo_uri}"
            local_photo_path = os.path.join(job_temp_dir, os.path.basename(photo_uri))
            download_file(photo_url, local_photo_path)
            
            face_encoding, _ = load_known_face(local_photo_path)
            if face_encoding is not None:
                known_faces.append(face_encoding)

        if not known_faces:
            raise HTTPException(status_code=400, detail="No valid faces found in the provided photos.")

        # Find scenes for all known faces
        all_scenes = []
        for face_encoding in known_faces:
            scenes = find_scenes_with_face(local_video_path, face_encoding)
            for start, end in scenes:
                all_scenes.append(Scene(start_time=start, end_time=end))
        
        # A simple way to merge overlapping scenes could be added here if needed
        return all_scenes

    finally:
        # Clean up temporary files
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)