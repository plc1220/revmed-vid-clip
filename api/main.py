import subprocess
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, UploadFile
from pydantic import BaseModel
import os
import uuid
import shutil
import asyncio
import fcntl
from dotenv import load_dotenv

load_dotenv()

# Import services
from services import gcs_service, video_service, ai_service

# --- Pydantic Models for API requests ---
class SplitRequest(BaseModel):
    gcs_bucket: str
    gcs_blob_name: str
    segment_duration: int # in seconds

class MetadataRequest(BaseModel):
    gcs_bucket: str
    gcs_video_uris: list[str]
    prompt_template: str
    ai_model_name: str
    gcs_output_prefix: str

class ClipGenerationRequest(BaseModel):
    gcs_bucket: str
    metadata_blob_name: str  # GCS path to the metadata file
    ai_prompt: str
    ai_model_name: str
    output_gcs_prefix: str

class JoinRequest(BaseModel):
    gcs_bucket: str
    clip_blob_names: list[str]
    output_gcs_prefix: str

class UploadResponse(BaseModel):
    gcs_bucket: str
    gcs_blob_name: str

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Rev-Med Video Processing API",
    description="An API for splitting, analyzing, and processing video files.",
    version="1.0.0"
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
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return data
    except (IOError, json.JSONDecodeError):
        # Return None if the file is locked or empty, allowing the client to retry
        return None

def _write_job(job_id: str, job_data: dict):
    job_path = _get_job_path(job_id)
    with open(job_path, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(job_data, f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

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
        _write_job(job_id, {"status": "in_progress", "details": f"Downloading gs://{request.gcs_bucket}/{request.gcs_blob_name}..."})
        print(f"Job {job_id}: Downloading gs://{request.gcs_bucket}/{request.gcs_blob_name}...")
        local_video_path = os.path.join(job_temp_dir, os.path.basename(request.gcs_blob_name))
        success, error = gcs_service.download_gcs_blob(request.gcs_bucket, request.gcs_blob_name, local_video_path)
        if not success:
            raise Exception(f"GCS Download failed: {error}")

        # 2. Split the video
        _write_job(job_id, {"status": "in_progress", "details": "Splitting video into segments..."})
        print(f"Job {job_id}: Splitting video into segments...")
        split_output_dir = os.path.join(job_temp_dir, "split_output")
        os.makedirs(split_output_dir, exist_ok=True)
        
        segment_paths, error = video_service.split_video(local_video_path, request.segment_duration, split_output_dir)
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
        output_prefix = os.path.join("segments", os.path.splitext(base_filename)[0] + "_segments/")
        
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
    This version consolidates metadata from all video segments into a single JSON file.
    """
    _write_job(job_id, {"status": "in_progress", "details": "Starting metadata generation."})
    print(f"Job {job_id}: Starting metadata generation for {len(request.gcs_video_uris)} videos.")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    all_metadata = []

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY environment variable not set.")
        
        success, error = ai_service.configure_genai(api_key)
        if not success:
            raise Exception(f"Failed to configure AI service: {error}")

        for i, gcs_uri in enumerate(request.gcs_video_uris):
            details = f"Processing video {i+1}/{len(request.gcs_video_uris)}: {os.path.basename(gcs_uri)}"
            _write_job(job_id, {"status": "in_progress", "details": details})
            print(f"Job {job_id}: {details}")

            prompt = request.prompt_template.replace("{{source_filename}}", os.path.basename(gcs_uri))
            
            metadata_json_str, error = await ai_service.generate_content_async(prompt, gcs_uri, request.ai_model_name)
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
                if isinstance(metadata_objects, list):
                    all_metadata.extend(metadata_objects)
                else:
                    print(f"Job {job_id}: Warning: AI response for {gcs_uri} was not a list. Skipping.")
            except json.JSONDecodeError as e:
                print(f"Job {job_id}: Failed to parse metadata JSON for {gcs_uri}. Error: {e}")
                continue

        if not all_metadata:
            _write_job(job_id, {"status": "completed", "details": "Metadata generation finished, but no valid metadata was produced."})
            print(f"Job {job_id}: No metadata was generated.")
            return

        # Determine a consolidated output filename from the segment folder name
        first_uri_path = request.gcs_video_uris[0].split(f"gs://{request.gcs_bucket}/")[1]
        segment_folder_name = os.path.dirname(first_uri_path).split('/')[-1]
        output_base_name = segment_folder_name.replace('_segments', '')
        
        consolidated_filename = f"{output_base_name}_metadata_consolidated.json"
        local_metadata_path = os.path.join(job_temp_dir, consolidated_filename)

        with open(local_metadata_path, 'w') as f:
            json.dump(all_metadata, f, indent=2)

        metadata_blob_name = os.path.join(request.gcs_output_prefix, consolidated_filename)
        _write_job(job_id, {"status": "in_progress", "details": f"Uploading consolidated metadata to {metadata_blob_name}"})
        
        success, upload_error = gcs_service.upload_gcs_blob(request.gcs_bucket, local_metadata_path, metadata_blob_name)
        if not success:
            raise Exception(f"Failed to upload consolidated metadata: {upload_error}")

        final_details = f"Successfully processed {len(request.gcs_video_uris)} videos. Consolidated metadata saved to gs://{request.gcs_bucket}/{metadata_blob_name}"
        _write_job(job_id, {"status": "completed", "details": final_details})
        print(f"Job {job_id}: {final_details}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_clip_generation(job_id: str, request: ClipGenerationRequest):
    """The actual logic for the clip generation background task."""
    _write_job(job_id, {"status": "in_progress", "details": "Starting clip generation."})
    print(f"Job {job_id}: Starting clip generation from {request.metadata_blob_name}.")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)

    try:
        # 1. Download metadata file from GCS
        _write_job(job_id, {"status": "in_progress", "details": "Downloading metadata file..."})
        local_metadata_path = os.path.join(job_temp_dir, os.path.basename(request.metadata_blob_name))
        success, error = gcs_service.download_gcs_blob(request.gcs_bucket, request.metadata_blob_name, local_metadata_path)
        if not success:
            raise Exception(f"Failed to download metadata file: {error}")

        with open(local_metadata_path, 'r') as f:
            metadata_content = f.read()

        # 2. Use AI to select clips from the metadata
        _write_job(job_id, {"status": "in_progress", "details": "Asking AI to select clips..."})
        print(f"Job {job_id}: Asking AI ({request.ai_model_name}) to select clips...")

        # Configure AI Service
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY environment variable not set.")
        success, error = ai_service.configure_genai(api_key)
        if not success:
            raise Exception(f"Failed to configure AI service: {error}")

        # Construct the prompt for the AI
        full_prompt = (
            f"Here is the metadata from a video analysis:\n\n"
            f"```json\n{metadata_content}\n```\n\n"
            f"Based on the metadata above, please fulfill the following request:\n"
            f"'{request.ai_prompt}'\n\n"
            f"Your task is to return a valid JSON array of objects, where each object represents a single clip to be created. "
            f"Each object must have 'source_filename', 'timestamp_start_end', and 'editor_note_clip_rationale' keys. "
            f"The 'source_filename' must match one of the source filenames mentioned in the metadata. "
            f"Do not include any text or formatting outside of the JSON array."
        )

        clips_json_str, error = ai_service.generate_content_sync(full_prompt, request.ai_model_name)
        if error:
            raise Exception(f"AI failed to generate clip list: {error}")
        
        try:
            # The AI might return a string with ```json ... ```, so we clean it up.
            if clips_json_str.strip().startswith("```json"):
                clips_json_str = clips_json_str.strip()[7:-3]
            selected_clips = json.loads(clips_json_str)
            if not isinstance(selected_clips, list):
                raise ValueError("AI response is not a JSON list.")
        except (json.JSONDecodeError, ValueError) as e:
            raise Exception(f"Invalid JSON response from AI for clip selection: {e}\nResponse was:\n{clips_json_str}")

        if not selected_clips:
            _write_job(job_id, {"status": "completed", "details": "AI did not select any clips to generate."})
            return

        # 3. Process each selected clip
        processed_clips_count = 0
        for i, clip_data in enumerate(selected_clips):
            source_filename = clip_data.get("source_filename")
            time_range = clip_data.get("timestamp_start_end")
            
            if not source_filename or not time_range:
                print(f"Job {job_id}: Skipping clip with missing data: {clip_data}")
                continue

            details = f"Processing clip {i+1}/{len(selected_clips)}: {source_filename} ({time_range})"
            _write_job(job_id, {"status": "in_progress", "details": details})
            print(f"Job {job_id}: {details}")

            # Determine the GCS path for the source video segment.
            # This logic assumes a parallel directory structure.
            # e.g., metadata in 'metadata/' and videos in 'processed/'
            # Correctly infer the source segment path.
            # The segments are in a folder derived from the original uploaded file's name.
            # The metadata file name itself gives us the clue.
            # e.g., METADATA_FILE is "...._test_part_001_metadata.json"
            # The original file base is "...._test"
            original_file_base = os.path.basename(request.metadata_blob_name).split('_part_')[0]
            
            # The metadata is in a path like "test_suite/RUN_ID/metadata/"
            # The segments are in "test_suite/RUN_ID/uploads/...._segments/"
            metadata_dir = os.path.dirname(request.metadata_blob_name)
            base_dir = os.path.dirname(metadata_dir) # This should be "test_suite/RUN_ID/"
            
            # This logic is still fragile. A better way is to make the path replacement
            # more intelligent. The key is that the segments are NOT in 'processed'.
            # They are in a subfolder of 'uploads' that ends with '_segments'.
            
            # Let's trace the path from the test script:
            # GCS_UPLOAD_PREFIX = f"test_suite/{TEST_RUN_ID}/uploads/"
            # gcs_blob_name = os.path.join(gcs_prefix, f"{job_id}_{file.filename}")
            # output_prefix for split = os.path.splitext(gcs_blob_name)[0] + "_segments/"
            
            # So, the segments are in a path that looks like:
            # "test_suite/RUN_ID/uploads/UPLOAD_ID_test_segments/SEGMENT_NAME.mp4"
            
            # The metadata is in:
            # "test_suite/RUN_ID/metadata/UPLOAD_ID_test_part_001_metadata.json"
            
            # We can reconstruct the segment path from the metadata path.
            
            # Correctly reconstruct the path to the video segment.
            # The metadata file name (e.g., "my_video_metadata_consolidated.json")
            # gives us the base name ("my_video").
            metadata_basename = os.path.basename(request.metadata_blob_name)
            if metadata_basename.endswith("_metadata_consolidated.json"):
                base_name = metadata_basename.replace("_metadata_consolidated.json", "")
                video_segment_folder = f"segments/{base_name}_segments"
                source_blob_name = os.path.join(video_segment_folder, source_filename)
            else:
                # Fallback for older, non-consolidated metadata files if needed.
                # This logic is fragile and should be removed once the transition is complete.
                if '_part_' in source_filename:
                    original_file_base = source_filename.split('_part_')[0]
                    video_segment_folder = f"segments/{original_file_base}_segments"
                    source_blob_name = os.path.join(video_segment_folder, source_filename)
                else:
                    raise Exception(f"Cannot determine segment folder for {source_filename} from metadata file {request.metadata_blob_name}")

            print(f"Job {job_id}: Inferred source blob name: {source_blob_name}")

            local_video_path = os.path.join(job_temp_dir, os.path.basename(source_blob_name))
            success, error = gcs_service.download_gcs_blob(request.gcs_bucket, source_blob_name, local_video_path)
            if not success:
                print(f"Job {job_id}: Failed to download source video {source_blob_name}. Skipping clip. Error: {error}")
                continue

            # Create the clip
            try:
                start_str, end_str = time_range.split(' - ')
                start_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], start_str.split(':')))
                end_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], end_str.split(':')))
            except (ValueError, AttributeError):
                print(f"Job {job_id}: Invalid time format '{time_range}'. Skipping clip.")
                continue

            clip_filename = f"{os.path.splitext(os.path.basename(source_blob_name))[0]}_clip_{i+1}.mp4"
            local_clip_output_dir = os.path.join(job_temp_dir, "clips_output")
            os.makedirs(local_clip_output_dir, exist_ok=True)
            final_clip_path = os.path.join(local_clip_output_dir, clip_filename)
            
            success, error = video_service.create_clip(local_video_path, final_clip_path, start_secs, end_secs)
            if not success:
                print(f"Job {job_id}: Failed to create clip {clip_filename}. Error: {error}")
                continue

            # Upload the clip to GCS
            clip_blob_name = os.path.join(request.output_gcs_prefix, clip_filename)
            success, error = gcs_service.upload_gcs_blob(request.gcs_bucket, final_clip_path, clip_blob_name)
            if not success:
                print(f"Job {job_id}: Failed to upload clip {clip_blob_name}. Error: {error}")
            else:
                processed_clips_count += 1

        _write_job(job_id, {"status": "completed", "details": f"Successfully generated and uploaded {processed_clips_count} clips."})
        print(f"Job {job_id}: Clip generation completed.")

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
        
        output_blob_name = os.path.join(request.output_gcs_prefix, output_filename)
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
async def upload_video_endpoint(file: UploadFile, gcs_bucket: str = Form(...), gcs_prefix: str = Form("uploads/")):
    """
    Uploads a video file to a temporary local path and then to GCS.
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
        gcs_blob_name = os.path.join(gcs_prefix, f"{job_id}_{file.filename}")
        success, error = gcs_service.upload_gcs_blob(gcs_bucket, local_video_path, gcs_blob_name)
        if not success:
            raise HTTPException(status_code=500, detail=f"GCS Upload failed: {error}")

        return UploadResponse(gcs_bucket=gcs_bucket, gcs_blob_name=gcs_blob_name)
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
