import os
import sys
import site
import cv2
import face_recognition
import time

# Ensure the virtual environment's site-packages is in the path
VENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'rev-med'))
SITE_PACKAGES = os.path.join(VENV_PATH, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')

if SITE_PACKAGES not in sys.path:
    sys.path.insert(0, SITE_PACKAGES)
from typing import List, Tuple

def load_known_face(image_path: str) -> Tuple[List, str]:
    """Loads a single face from an image file."""
    try:
        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)
        if encodings:
            return encodings[0], os.path.basename(image_path)
        else:
            return None, ""
    except Exception as e:
        print(f"Error loading face from {image_path}: {e}")
        return None, ""

def find_scenes_with_face(
    video_path: str,
    known_face_encoding: List,
    known_face_name: str,
    frame_skip: int = 5
) -> List[Tuple[float, float]]:
    """
    Analyzes a video to find scenes containing a specific face.
    """
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

def format_time(seconds: float) -> str:
    """Converts seconds to HH:MM:SS.ms format."""
    return time.strftime('%H:%M:%S', time.gmtime(seconds)) + f".{int((seconds % 1) * 1000)}"