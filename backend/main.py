import subprocess
import json
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uuid
import shutil
import asyncio
from dotenv import load_dotenv
import sys
import google.auth

# Add the backend directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

load_dotenv()

# Import services
import gcs_service
import video_service
import ai_service
import requests

# --- Pydantic Models for API requests ---
class FaceClipGenerationRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_video_uri: str
    gcs_cast_photo_uris: list[str]
    output_gcs_prefix: str

class SplitRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_blob_name: str
    segment_duration: int # in seconds

class MetadataRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_video_uris: list[str]
    prompt_template: str
    ai_model_name: str
    gcs_output_prefix: str

class ClipGenerationRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    metadata_blob_names: list[str]  # GCS paths to the metadata files
    output_gcs_prefix: str

class JoinRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    clip_blob_names: list[str]
    output_gcs_prefix: str

class GCSDeleteRequest(BaseModel):
    gcs_bucket: str
    blob_name: str

class GCSDeleteBatchRequest(BaseModel):
    gcs_bucket: str
    blob_names: list[str]

class UploadResponse(BaseModel):
    gcs_bucket: str
    gcs_blob_name: str
    workspace: str

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Rev-Med Video Processing API",
    description="An API for splitting, analyzing, and processing video files.",
    version="1.0.0"
)

# --- CORS Configuration ---
# This allows the frontend (running on http://localhost:8501) to communicate with the backend.
origins = [
    "http://localhost",
    "http://localhost:8501",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Access-Control-Allow-Private-Network"],
)

# --- File-based Job Store ---
JOB_STORE_PATH = "./job_store"
os.makedirs(JOB_STORE_PATH, exist_ok=True)

def _get_job_path(job_id: str) -> str:
    return os.path.join(JOB_STORE_PATH, f"{job_id}.json")

def _read_job(job_id: str) -> dict:
    job_path = _get_job_path(job_id)
    if not os.path.exists(job_path):
        return None
    try:
        with open(job_path, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # If the file is empty or malformed, return None
                return None
        return data
    except (IOError, json.JSONDecodeError):
        # Return None if the file is locked or empty, allowing the client to retry
        return None

def _write_job(job_id: str, job_data: dict):
    job_path = _get_job_path(job_id)
    with open(job_path, 'w') as f:
        json.dump(job_data, f)

# --- Temporary Storage Configuration ---
TEMP_STORAGE_PATH = "./api_temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

# --- Background Task Implementations ---

def process_splitting(job_id: str, request: SplitRequest):
    """The actual logic for the video splitting background task."""
    _write_job(job_id, {"status": "in_progress", "details": "Starting video split process."})
    print(f"Job {job_id}: Starting video split process.")
    
    # Create a unique temporary directory for this job
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    try:
        # 1. Download video from GCS
        # The GCS bucket is mounted at /gcs. No need to download.
        gcs_mounted_video_path = os.path.join("/gcs", request.gcs_blob_name)
        
        if not os.path.exists(gcs_mounted_video_path):
            raise Exception(f"Video file not found at mounted path: {gcs_mounted_video_path}")

        _write_job(job_id, {"status": "in_progress", "details": f"Processing video from mounted path: {gcs_mounted_video_path}"})
        print(f"Job {job_id}: Processing video from mounted path: {gcs_mounted_video_path}")

        # 2. Split the video directly from the mounted GCS path
        _write_job(job_id, {"status": "in_progress", "details": "Splitting video into segments..."})
        print(f"Job {job_id}: Splitting video into segments...")
        split_output_dir = os.path.join(job_temp_dir, "split_output")
        os.makedirs(split_output_dir, exist_ok=True)
        
        segment_paths, error = video_service.split_video(gcs_mounted_video_path, request.segment_duration, split_output_dir)
        if error:
            # Even if there's an error, some segments might have been created. We'll upload them.
            _write_job(job_id, {"status": "in_progress", "details": f"Splitting partially failed: {error}. Uploading successful segments."})
        
        if not segment_paths:
            raise Exception("Video splitting produced no segments.")

        # 3. Upload segments back to GCS
        _write_job(job_id, {"status": "in_progress", "details": f"Uploading {len(segment_paths)} segments to GCS..."})
        print(f"Job {job_id}: Uploading {len(segment_paths)} segments to GCS...")
        # Create a clean output prefix in a dedicated 'segments' folder
        base_filename = os.path.basename(request.gcs_blob_name)
        output_prefix = os.path.join(request.workspace, "segments", os.path.splitext(base_filename)[0] + "_segments/")
        
        for i, segment_path in enumerate(segment_paths):
            segment_blob_name = os.path.join(output_prefix, os.path.basename(segment_path))
            _write_job(job_id, {"status": "in_progress", "details": f"Uploading segment {i+1}/{len(segment_paths)}: {segment_blob_name}"})
            print(f"Job {job_id}: Uploading segment {i+1}/{len(segment_paths)}: {segment_blob_name}")
            success, upload_error = gcs_service.upload_gcs_blob(request.gcs_bucket, segment_path, segment_blob_name)
            if not success:
                # Log error but continue trying to upload others
                print(f"Warning: Failed to upload {segment_path}: {upload_error}")

        _write_job(job_id, {"status": "completed", "details": f"Successfully split video into {len(segment_paths)} segments in gs://{request.gcs_bucket}/{output_prefix}"})
        print(f"Job {job_id}: Successfully split video into {len(segment_paths)} segments in gs://{request.gcs_bucket}/{output_prefix}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        # Clean up the temporary directory for this job
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

async def process_metadata_generation(job_id: str, request: MetadataRequest):
    """
    The actual logic for the metadata generation background task.
    This version generates one metadata JSON file per video segment.
    """
    _write_job(job_id, {"status": "in_progress", "details": "Starting metadata generation."})
    print(f"Job {job_id}: Starting metadata generation for {len(request.gcs_video_uris)} videos.")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    processed_files_count = 0
    generated_metadata_files = []

    try:
        # The AI service is now configured automatically via environment variables.
        # No explicit configuration call is needed.

        for i, gcs_uri in enumerate(request.gcs_video_uris):
            video_basename = os.path.basename(gcs_uri)
            details = f"Processing video {i+1}/{len(request.gcs_video_uris)}: {video_basename}"
            _write_job(job_id, {"status": "in_progress", "details": details})
            print(f"Job {job_id}: {details}")

            # Download the video to get its duration
            local_video_path = os.path.join(job_temp_dir, video_basename)
            success, download_error = gcs_service.download_gcs_blob(request.gcs_bucket, gcs_uri.split(f"gs://{request.gcs_bucket}/")[1], local_video_path)
            if not success:
                print(f"Job {job_id}: Failed to download video {gcs_uri} to get duration. Skipping. Error: {download_error}")
                continue

            duration_seconds, duration_error = video_service.get_video_duration(local_video_path)
            if duration_error:
                print(f"Job {job_id}: Failed to get duration for {gcs_uri}. Skipping. Error: {duration_error}")
                os.remove(local_video_path) # Clean up
                continue
            
            # Format duration to HH:MM:SS
            duration_str = f"{int(duration_seconds // 3600):02d}:{int((duration_seconds % 3600) // 60):02d}:{int(duration_seconds % 60):02d}"

            prompt = request.prompt_template.replace("{{source_filename}}", video_basename)
            prompt = prompt.replace("{{actual_video_duration}}", duration_str)
            
            metadata_json_str, error = await ai_service.generate_content_async(prompt, gcs_uri, request.ai_model_name)
            
            # Clean up the downloaded video file
            os.remove(local_video_path)
            if error:
                print(f"Job {job_id}: Failed to generate metadata for {gcs_uri}. Error: {error}")
                continue
            if not metadata_json_str:
                print(f"Job {job_id}: No metadata generated for {gcs_uri}. Skipping.")
                continue

            try:
                if metadata_json_str.strip().startswith("```json"):
                    metadata_json_str = metadata_json_str.strip()[7:-3]
                metadata_objects = json.loads(metadata_json_str)
                
                validated_metadata = []
                if isinstance(metadata_objects, list):
                    for obj in metadata_objects:
                        if isinstance(obj, dict):
                            # Validate timestamp
                            timestamp = obj.get("timestamp_start_end")
                            if timestamp:
                                try:
                                    start_str, end_str = timestamp.split(' - ')
                                    end_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], end_str.split(':')))
                                    if end_secs <= duration_seconds:
                                        obj['source_filename'] = gcs_uri
                                        validated_metadata.append(obj)
                                    else:
                                        print(f"Job {job_id}: Discarding invalid timestamp {timestamp} for video {gcs_uri} with duration {duration_seconds}s.")
                                except (ValueError, AttributeError):
                                    print(f"Job {job_id}: Discarding malformed timestamp '{timestamp}' for video {gcs_uri}.")
                            else:
                                print(f"Job {job_id}: Discarding metadata object with missing timestamp for video {gcs_uri}.")
                
                if not validated_metadata:
                    print(f"Job {job_id}: No valid metadata generated for {gcs_uri} after validation. Skipping.")
                    continue

                # Even if the AI returns a list, we save it to a file specific to this video.
                output_filename = f"{os.path.splitext(video_basename)[0]}_metadata.json"
                local_metadata_path = os.path.join(job_temp_dir, output_filename)

                with open(local_metadata_path, 'w') as f:
                    json.dump(validated_metadata, f, indent=2)

                # Upload the individual metadata file
                metadata_blob_name = os.path.join(request.workspace, request.gcs_output_prefix, output_filename)
                upload_details = f"Uploading metadata for {video_basename} to {metadata_blob_name}"
                _write_job(job_id, {"status": "in_progress", "details": upload_details})
                print(f"Job {job_id}: {upload_details}")

                success, upload_error = gcs_service.upload_gcs_blob(request.gcs_bucket, local_metadata_path, metadata_blob_name)
                if success:
                    processed_files_count += 1
                    generated_metadata_files.append(f"gs://{request.gcs_bucket}/{metadata_blob_name}")
                else:
                    print(f"Job {job_id}: Failed to upload metadata for {video_basename}. Error: {upload_error}")

            except json.JSONDecodeError as e:
                print(f"Job {job_id}: Failed to parse metadata JSON for {gcs_uri}. Error: {e}")
                continue

        if processed_files_count == 0:
            final_details = "Metadata generation finished, but no valid metadata was produced or uploaded."
        else:
            final_details = f"Successfully generated and uploaded {processed_files_count} metadata file(s)."

        _write_job(job_id, {"status": "completed", "details": final_details, "generated_files": generated_metadata_files})
        print(f"Job {job_id}: {final_details}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_clip_generation(job_id: str, request: ClipGenerationRequest):
    """
    The actual logic for the clip generation background task.
    This optimized version groups clips by source video to download each video only once.
    """
    _write_job(job_id, {"status": "in_progress", "details": "Starting clip generation."})
    print(f"Job {job_id}: Starting clip generation from {len(request.metadata_blob_names)} metadata file(s).")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    total_processed_clips_count = 0
    generated_clips_paths = []
    clips_by_source_video = {} # Key: source_blob_name, Value: list of clip_data

    try:
        # --- Step 1: Aggregate all clips from metadata files and group by source video ---
        _write_job(job_id, {"status": "in_progress", "details": "Aggregating and grouping clips from metadata..."})
        print(f"Job {job_id}: Aggregating clips from {len(request.metadata_blob_names)} metadata files.")

        for metadata_blob_name in request.metadata_blob_names:
            local_metadata_path = os.path.join(job_temp_dir, os.path.basename(metadata_blob_name))
            success, error = gcs_service.download_gcs_blob(request.gcs_bucket, metadata_blob_name, local_metadata_path)
            if not success:
                print(f"Job {job_id}: Failed to download metadata {metadata_blob_name}. Skipping. Error: {error}")
                continue

            with open(local_metadata_path, 'r') as f:
                metadata_content = f.read()

            try:
                if metadata_content.strip().startswith("```json"):
                    metadata_content = metadata_content.strip()[7:-3]
                selected_clips = json.loads(metadata_content)
                if not isinstance(selected_clips, list):
                    selected_clips = [selected_clips] if isinstance(selected_clips, dict) else []

                for clip_data in selected_clips:
                    source_gcs_uri = clip_data.get("source_filename")
                    if not source_gcs_uri:
                        continue
                    
                    # Parse GCS URI to get blob name
                    if source_gcs_uri.startswith(f"gs://{request.gcs_bucket}/"):
                        source_blob_name = source_gcs_uri.split(f"gs://{request.gcs_bucket}/", 1)[1]
                        if source_blob_name not in clips_by_source_video:
                            clips_by_source_video[source_blob_name] = []
                        clips_by_source_video[source_blob_name].append(clip_data)
                    else:
                        print(f"Job {job_id}: Skipping clip with invalid or mismatched GCS URI: {source_gcs_uri}")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"Job {job_id}: Invalid JSON in {metadata_blob_name}. Error: {e}")
                continue
        
        # --- Step 2: Process clips for each source video ---
        total_source_videos = len(clips_by_source_video)
        print(f"Job {job_id}: Found {sum(len(c) for c in clips_by_source_video.values())} clips to generate from {total_source_videos} unique source videos.")

        for i, (source_blob_name, clips_to_create) in enumerate(clips_by_source_video.items()):
            details = f"Processing source video {i+1}/{total_source_videos}: {source_blob_name}"
            _write_job(job_id, {"status": "in_progress", "details": details})
            print(f"Job {job_id}: {details}")

            # Download the source video ONCE
            local_video_path = os.path.join(job_temp_dir, os.path.basename(source_blob_name))
            print(f"Job {job_id}: Downloading source video: gs://{request.gcs_bucket}/{source_blob_name}")
            success, error = gcs_service.download_gcs_blob(request.gcs_bucket, source_blob_name, local_video_path)
            if not success:
                print(f"Job {job_id}: Failed to download {source_blob_name}. Skipping all clips for this video. Error: {error}")
                continue

            # Create all clips from this one downloaded video
            for clip_data in clips_to_create:
                time_range = clip_data.get("timestamp_start_end")
                if not time_range:
                    print(f"Job {job_id}: Skipping clip with missing 'timestamp_start_end': {clip_data}")
                    continue

                try:
                    start_str, end_str = time_range.split(' - ')
                    start_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], start_str.split(':')))
                    end_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], end_str.split(':')))
                except (ValueError, AttributeError):
                    print(f"Job {job_id}: Invalid time format '{time_range}'. Skipping clip.")
                    continue

                clip_filename = f"{os.path.splitext(os.path.basename(source_blob_name))[0]}_clip_{total_processed_clips_count + 1}.mp4"
                local_clip_output_dir = os.path.join(job_temp_dir, "clips_output")
                os.makedirs(local_clip_output_dir, exist_ok=True)
                final_clip_path = os.path.join(local_clip_output_dir, clip_filename)
                
                success, error = video_service.create_clip(local_video_path, final_clip_path, start_secs, end_secs)
                if not success:
                    print(f"Job {job_id}: Failed to create clip {clip_filename}. Error: {error}")
                    continue

                clip_blob_name = os.path.join(request.workspace, request.output_gcs_prefix, clip_filename)
                success, error = gcs_service.upload_gcs_blob(request.gcs_bucket, final_clip_path, clip_blob_name)
                if not success:
                    print(f"Job {job_id}: Failed to upload clip {clip_blob_name}. Error: {error}")
                else:
                    total_processed_clips_count += 1
                    generated_clips_paths.append(clip_blob_name)
            
            # Clean up the downloaded source video to save space
            if os.path.exists(local_video_path):
                os.remove(local_video_path)

        final_details = f"Successfully generated and uploaded {total_processed_clips_count} clips from {len(clips_by_source_video)} unique videos."
        _write_job(job_id, {"status": "completed", "details": final_details, "generated_clips": generated_clips_paths})
        print(f"Job {job_id}: Clip generation completed.")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_face_clip_generation(job_id: str, request: FaceClipGenerationRequest):
    """Orchestrates face recognition-based clip generation by calling the microservice."""
    _write_job(job_id, {"status": "in_progress", "details": "Starting face recognition clip generation."})
    print(f"Job {job_id}: Calling face recognition microservice for video {request.gcs_video_uri}.")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    generated_clips_paths = []

    try:
        # 1. Call the face recognition microservice
        fr_service_url = "http://face-recognition-service:8001/process-video/"
        payload = {
            "gcs_bucket": request.gcs_bucket,
            "gcs_video_uri": request.gcs_video_uri,
            "gcs_cast_photo_uris": request.gcs_cast_photo_uris,
        }
        response = requests.post(fr_service_url, json=payload)
        response.raise_for_status()
        scenes = response.json()

        if not scenes:
            _write_job(job_id, {"status": "completed", "details": "No scenes found with the specified cast members.", "generated_clips": []})
            return

        # 2. Download the source video once for clipping
        _write_job(job_id, {"status": "in_progress", "details": f"Downloading video for clipping: {request.gcs_video_uri}"})
        video_basename = os.path.basename(request.gcs_video_uri)
        local_video_path = os.path.join(job_temp_dir, video_basename)
        success, error = gcs_service.download_gcs_blob(request.gcs_bucket, request.gcs_video_uri, local_video_path)
        if not success:
            raise Exception(f"Failed to download video {request.gcs_video_uri}: {error}")

        # 3. Create and upload clips based on the scenes returned by the microservice
        for i, scene in enumerate(scenes):
            start_sec, end_sec = scene["start_time"], scene["end_time"]
            details = f"Generating clip {i+1}/{len(scenes)}..."
            _write_job(job_id, {"status": "in_progress", "details": details})
            
            clip_filename = f"{os.path.splitext(video_basename)[0]}_face_clip_{i+1}.mp4"
            local_clip_path = os.path.join(job_temp_dir, clip_filename)

            success, error = video_service.create_clip(local_video_path, local_clip_path, start_sec, end_sec)
            if not success:
                print(f"Job {job_id}: Failed to create clip {clip_filename}. Error: {error}")
                continue

            clip_blob_name = os.path.join(request.workspace, request.output_gcs_prefix, clip_filename)
            success, error = gcs_service.upload_gcs_blob(request.gcs_bucket, local_clip_path, clip_blob_name)
            if success:
                generated_clips_paths.append(clip_blob_name)
            else:
                print(f"Job {job_id}: Failed to upload clip {clip_blob_name}. Error: {error}")

        final_details = f"Successfully generated {len(generated_clips_paths)} clips based on face recognition."
        _write_job(job_id, {"status": "completed", "details": final_details, "generated_clips": generated_clips_paths})
        print(f"Job {job_id}: {final_details}")

    except requests.exceptions.RequestException as e:
        _write_job(job_id, {"status": "failed", "details": f"Failed to connect to face recognition service: {e}"})
    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_video_joining(job_id: str, request: JoinRequest):
    """The actual logic for the video joining background task."""
    _write_job(job_id, {"status": "in_progress", "details": "Starting video joining process."})
    print(f"Job {job_id}: Starting to join {len(request.clip_blob_names)} clips.")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    local_clip_paths = []
    try:
        # 1. Download all clips from GCS
        for i, blob_name in enumerate(request.clip_blob_names):
            details = f"Downloading clip {i+1}/{len(request.clip_blob_names)}: {os.path.basename(blob_name)}"
            _write_job(job_id, {"status": "in_progress", "details": details})
            print(f"Job {job_id}: {details}")

            local_path = os.path.join(job_temp_dir, os.path.basename(blob_name))
            success, error = gcs_service.download_gcs_blob(request.gcs_bucket, blob_name, local_path)
            if not success:
                raise Exception(f"Failed to download clip {blob_name}: {error}")
            local_clip_paths.append(local_path)

        # 2. Join the videos
        _write_job(job_id, {"status": "in_progress", "details": "Joining video clips..."})
        print(f"Job {job_id}: Joining video clips...")
        
        # Create a unique name for the output file
        output_filename = f"joined_video_{job_id}.mp4"
        local_output_path = os.path.join(job_temp_dir, output_filename)

        success, error = video_service.join_videos(local_clip_paths, local_output_path)
        if not success:
            raise Exception(f"Failed to join videos: {error}")

        # 3. Upload the final video to GCS
        _write_job(job_id, {"status": "in_progress", "details": "Uploading final video..."})
        print(f"Job {job_id}: Uploading final video...")
        
        output_blob_name = os.path.join(request.workspace, request.output_gcs_prefix, output_filename)
        success, error = gcs_service.upload_gcs_blob(request.gcs_bucket, local_output_path, output_blob_name)
        if not success:
            raise Exception(f"Failed to upload final video: {error}")

        final_details = f"Successfully joined {len(request.clip_blob_names)} clips into gs://{request.gcs_bucket}/{output_blob_name}"
        _write_job(job_id, {"status": "completed", "details": final_details})
        print(f"Job {job_id}: {final_details}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)


# --- API Endpoints ---

@app.get("/", tags=["Health Check"])
async def read_root():
    """Health check endpoint to confirm the API is running."""
    return {"status": "API is running"}

@app.post("/upload-video/", tags=["Video Processing"], response_model=UploadResponse)
async def upload_video_endpoint(
    file: UploadFile,
    gcs_bucket: str = Form(...),
    workspace: str = Form(...),
    gcs_prefix: str = Form("uploads/")
):
    """
    Uploads a video file to a temporary local path and then to a workspace-specific folder in GCS.
    """
    job_id = str(uuid.uuid4())
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)

    local_video_path = os.path.join(job_temp_dir, file.filename)

    try:
        # Save uploaded file locally
        with open(local_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Upload to GCS
        # All uploads now go into a workspace folder
        gcs_blob_name = os.path.join(workspace, gcs_prefix, f"{job_id}_{file.filename}")
        
        success, error = gcs_service.upload_gcs_blob(gcs_bucket, local_video_path, gcs_blob_name)
        if not success:
            raise HTTPException(status_code=500, detail=f"GCS Upload failed: {error}")

        return UploadResponse(gcs_bucket=gcs_bucket, gcs_blob_name=gcs_blob_name, workspace=workspace)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp directory
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

@app.post("/split-video/", tags=["Video Processing"], status_code=202)
async def split_video_endpoint(request: SplitRequest, background_tasks: BackgroundTasks):
    """
    Downloads a video from GCS, splits it into segments, and uploads them back.
    This process runs in the background.
    """
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "pending", "details": "Job has been accepted and is waiting to start."})
    background_tasks.add_task(process_splitting, job_id, request)
    return {"message": "Video splitting job started.", "job_id": job_id}

@app.post("/generate-metadata/", tags=["AI Processing"], status_code=202)
async def generate_metadata_endpoint(request: MetadataRequest, background_tasks: BackgroundTasks):
    """
    Generates metadata for a list of videos using the Gemini API.
    This process runs in the background.
    """
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "pending", "details": "Job has been accepted and is waiting to start."})
    background_tasks.add_task(process_metadata_generation, job_id, request)
    return {"message": "Metadata generation job started.", "job_id": job_id}

@app.post("/generate-clips/", tags=["Video Processing"], status_code=202)
async def generate_clips_endpoint(request: ClipGenerationRequest, background_tasks: BackgroundTasks):
    """
    Generates video clips based on an AI-generated metadata file.
    This process runs in the background.
    """
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "pending", "details": "Job has been accepted and is waiting to start."})
    background_tasks.add_task(process_clip_generation, job_id, request)
    return {"message": "Clip generation job started.", "job_id": job_id}

@app.post("/generate-clips-by-face/", tags=["Video Processing"], status_code=202)
async def generate_clips_by_face_endpoint(request: FaceClipGenerationRequest, background_tasks: BackgroundTasks):
    """
    Generates clips from a video based on face recognition of specified cast members.
    """
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "pending", "details": "Job received for face-based clip generation."})
    background_tasks.add_task(process_face_clip_generation, job_id, request)
    return {"job_id": job_id}

@app.get("/workspaces/", tags=["Workspaces"])
async def list_workspaces_endpoint(gcs_bucket: str):
    """
    Lists all available workspaces (top-level folders) in the GCS bucket.
    """
    workspaces, error = gcs_service.list_workspaces(gcs_bucket)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"workspaces": workspaces}

@app.post("/workspaces/", tags=["Workspaces"], status_code=201)
async def create_workspace_endpoint(workspace_name: str, gcs_bucket: str):
    """
    Creates a new workspace by setting up its folder structure in GCS.
    """
    success, message = gcs_service.create_workspace(gcs_bucket, workspace_name)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}

@app.post("/join-videos/", tags=["Video Processing"], status_code=202)
async def join_videos_endpoint(request: JoinRequest, background_tasks: BackgroundTasks):
    """
    Joins a list of video clips into a single video.
    This process runs in the background.
    """
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "pending", "details": "Job has been accepted and is waiting to start."})
    background_tasks.add_task(process_video_joining, job_id, request)
    return {"message": "Video joining job started.", "job_id": job_id}

# --- Job Status Endpoint ---
@app.get("/jobs/{job_id}", tags=["Jobs"])
async def get_job_status(job_id: str):
    """
    Retrieves the status of a background job.
    """
    job = _read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.delete("/delete-gcs-blob/", tags=["GCS"])
async def delete_gcs_blob_endpoint(request: GCSDeleteRequest):
    """
    Deletes a specific blob from a GCS bucket.
    """
    success, error = gcs_service.delete_gcs_blob(request.gcs_bucket, request.blob_name)
    if not success:
        raise HTTPException(status_code=404, detail=error)
    return {"message": f"Blob {request.blob_name} deleted successfully."}


@app.post("/gcs/delete-batch", tags=["GCS"])
async def delete_gcs_blobs_batch_endpoint(request: GCSDeleteBatchRequest):
    """
    Deletes a batch of blobs from a specified GCS bucket.
    """
    deleted_files = []
    failed_files = {}

    for blob_name in request.blob_names:
        success, error = gcs_service.delete_gcs_blob(request.gcs_bucket, blob_name)
        if success:
            deleted_files.append(blob_name)
        else:
            failed_files[blob_name] = error
    
    if failed_files:
        return {"deleted_files": deleted_files, "failed_files": failed_files}

    return {"deleted_files": deleted_files, "failed_files": {}}

@app.get("/gcs/list", tags=["GCS"])
async def gcs_list_endpoint(gcs_bucket: str, prefix: str):
    """Lists files in a GCS bucket."""
    files, error = gcs_service.list_gcs_files(gcs_bucket, prefix)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"files": files}

@app.get("/gcs/signed-url", tags=["GCS"])
async def gcs_signed_url_endpoint(gcs_bucket: str, blob_name: str):
    """Generates a signed URL for a GCS blob."""
    url, error = gcs_service.generate_signed_url(gcs_bucket, blob_name)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"url": url}
class UploadURLRequest(BaseModel):
    file_name: str
    content_type: str
    workspace: str
    gcs_bucket: str

@app.post("/gcs/generate-upload-url", tags=["GCS"])
async def gcs_generate_upload_url_endpoint(payload: UploadURLRequest):
    """
    Generates a v4 signed URL for uploading a file directly to GCS.
    """
    try:
        # Construct the blob name within the workspace's uploads folder
        blob_name = os.path.join(payload.workspace, "uploads", payload.file_name)
        
        signed_url, error = gcs_service.generate_v4_signed_upload_url(
            bucket_name=payload.gcs_bucket,
            blob_name=blob_name,
            content_type=payload.content_type
        )
        
        if error:
            raise HTTPException(status_code=500, detail=error)
            
        return {"signed_url": signed_url, "gcs_blob_name": blob_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@app.get("/gcs/download", tags=["GCS"])
async def gcs_download_endpoint(gcs_bucket: str, blob_name: str):
    """Downloads a blob from GCS."""
    # Create a temporary file to download to
    temp_dir = "temp_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    local_file_path = os.path.join(temp_dir, os.path.basename(blob_name))

    success, error = gcs_service.download_gcs_blob(gcs_bucket, blob_name, local_file_path)
    if not success:
        raise HTTPException(status_code=500, detail=error)

    with open(local_file_path, 'r') as f:
        content = json.load(f)

    # Clean up the temp file
    os.remove(local_file_path)

    return content
