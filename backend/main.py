import json
import os
import uuid
import shutil

from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware

# Import schemas
from schemas import (
    UploadURLRequest,
    UploadURLResponse,
    FaceClipGenerationRequest,
    SplitRequest,
    MetadataRequest,
    ClipGenerationRequest,
    JoinRequest,
    GCSDeleteRequest,
    GCSBatchDeleteRequest,
    UploadResponse,
)

load_dotenv()

# Import services
from logging_config import setup_logging
import gcs_service
import video_service
import ai_service
import requests
import task_service

# Setup logging
setup_logging()

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Rev-Med Video Processing API",
    description="An API for splitting, analyzing, and processing video files.",
    version="1.0.0",
)

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
        with open(job_path, "r") as f:
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
    with open(job_path, "w") as f:
        json.dump(job_data, f)


# --- Temporary Storage Configuration ---
TEMP_STORAGE_PATH = "./api_temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

# --- Helper Functions ---

def _queue_background_job(background_tasks: BackgroundTasks, task_function, request):
    job_id = str(uuid.uuid4())
    _write_job(job_id, {"status": "queued"})
    background_tasks.add_task(task_function, job_id, request)
    return {"job_id": job_id, "status": "queued"}

# --- API Endpoints ---

@app.get("/", tags=["Health Check"])
async def read_root():
    """A simple health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/workspaces/", tags=["Workspaces"])
async def list_workspaces(gcs_bucket: str = Query(None)):
    """Lists all workspaces in a GCS bucket."""
    try:
        workspaces, error = gcs_service.list_workspaces(gcs_bucket)
        if error:
            raise HTTPException(status_code=500, detail=error)
        return {"workspaces": workspaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gcs/list", tags=["GCS"])
async def list_gcs_files_endpoint(gcs_bucket: str = Query(None), prefix: str = Query("")):
    """Lists files in a GCS bucket with a given prefix."""
    try:
        files, error = gcs_service.list_gcs_files(gcs_bucket, prefix)
        if error:
            # Distinguish between a folder not found and other errors
            if "No files found" in error:
                raise HTTPException(status_code=404, detail=error)
            else:
                raise HTTPException(status_code=500, detail=error)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workspaces/", tags=["Workspaces"])
async def create_workspace(gcs_bucket: str = Query(None), workspace_name: str = Query(None)):
    """Creates a new workspace in a GCS bucket."""
    try:
        gcs_service.create_workspace(gcs_bucket, workspace_name)
        return {"message": f"Workspace '{workspace_name}' created successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Job Management Endpoints ---

@app.get("/jobs/{job_id}", tags=["Jobs"])
async def get_job_status(job_id: str):
    """Retrieves the status of a background job with enhanced transcoder details."""
    job = _read_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # If this is a transcoder job and still in progress, get live status
    if (job.get("transcoder_job_name") and
        job.get("status") in ["submitted", "in_progress"]):
        
        try:
            from task_service import get_transcoder_job_status  # Import your helper
            transcoder_state, transcoder_details = get_transcoder_job_status(
                job["transcoder_job_name"]
            )
            
            # Update job status based on transcoder state
            if transcoder_state == "SUCCEEDED":
                job["status"] = "completed"
                job["details"] = f"Video splitting completed successfully. {job.get('num_segments', 'Multiple')} segments created."
                _write_job(job_id, job)  # Persist the update
                
            elif transcoder_state == "FAILED":
                job["status"] = "failed"
                job["details"] = transcoder_details
                _write_job(job_id, job)
                
            elif transcoder_state in ["RUNNING", "PENDING"]:
                job["status"] = "in_progress"
                job["details"] = f"Transcoder job {transcoder_state.lower()}..."
                # Don't persist these temporary updates
            
            # Add transcoder-specific info to response
            job["transcoder_status"] = {
                "state": transcoder_state,
                "details": transcoder_details
            }
            
        except Exception as e:
            # If transcoder status check fails, return existing job info
            logging.warning(f"Failed to get transcoder status for job {job_id}: {e}")
    
    return job

@app.post("/generate-upload-url/", response_model=UploadURLResponse)
async def generate_upload_url(request: UploadURLRequest):
    """
    Generate a signed URL for direct upload to Google Cloud Storage.
    
    Args:
        request: Contains file_name, content_type, gcs_bucket, and workspace
        
    Returns:
        UploadURLResponse with the signed URL and blob name
    """
    
    try:
        # Validate file extension (optional - add your allowed extensions)
        allowed_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
        file_extension = os.path.splitext(request.file_name.lower())[1]
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file_extension} not supported. Allowed: {allowed_extensions}"
            )
        
        # Generate unique blob name to avoid conflicts
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        safe_filename = request.file_name.replace(" ", "_").replace("/", "_")
        
        # Create blob path: workspace/uploads/timestamp_uniqueid_filename
        gcs_blob_name = f"{request.workspace}/uploads/{timestamp}_{unique_id}_{safe_filename}"
        
        signed_url, error = gcs_service.generate_signed_url(
            bucket_name=request.gcs_bucket,
            blob_name=gcs_blob_name,
            method="PUT",
            content_type=request.content_type,
        )
        
        return UploadURLResponse(
            upload_url=signed_url,
            gcs_blob_name=gcs_blob_name
        )
        
    except Exception as e:
        print(f"Error generating signed URL: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate upload URL: {str(e)}"
        )


@app.post("/upload-video/", tags=["Video Processing"], response_model=UploadResponse)
async def upload_video_endpoint(
    workspace: str = Form(...),
    gcs_bucket: str = Form(...),
    video_file: UploadFile = Form(...),
):
    """
    Handles direct video uploads to the server, then to GCS.
    """
    # Create a unique temporary directory for this upload
    upload_id = str(uuid.uuid4())
    temp_dir = os.path.join(TEMP_STORAGE_PATH, "uploads", upload_id)
    os.makedirs(temp_dir, exist_ok=True)
    local_video_path = os.path.join(temp_dir, video_file.filename)

    try:
        # Save the uploaded file locally first
        with open(local_video_path, "wb") as buffer:
            shutil.copyfileobj(video_file.file, buffer)

        # Define the GCS blob name
        gcs_blob_name = os.path.join(workspace, "videos", video_file.filename)

        # Upload the local file to GCS
        success, error = gcs_service.upload_gcs_blob(gcs_bucket, local_video_path, gcs_blob_name)
        if not success:
            raise HTTPException(status_code=500, detail=f"GCS Upload failed: {error}")

        return UploadResponse(
            gcs_bucket=gcs_bucket,
            gcs_blob_name=gcs_blob_name,
            workspace=workspace,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up the temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


@app.post("/upload-cast-photo/", tags=["Video Processing"], response_model=UploadResponse)
async def upload_cast_photo_endpoint(
    photo_file: UploadFile,
    workspace: str = Query(...),
    gcs_bucket: str = Query(...),
):
    """
    Handles direct cast photo uploads to the server, then to GCS.
    """
    upload_id = str(uuid.uuid4())
    temp_dir = os.path.join(TEMP_STORAGE_PATH, "uploads", upload_id)
    os.makedirs(temp_dir, exist_ok=True)
    local_photo_path = os.path.join(temp_dir, photo_file.filename)

    try:
        with open(local_photo_path, "wb") as buffer:
            shutil.copyfileobj(photo_file.file, buffer)

        gcs_blob_name = os.path.join(workspace, "temp_cast_photos", photo_file.filename)

        success, error = gcs_service.upload_gcs_blob(gcs_bucket, local_photo_path, gcs_blob_name)
        if not success:
            raise HTTPException(status_code=500, detail=f"GCS Upload failed: {error}")

        return UploadResponse(
            gcs_bucket=gcs_bucket,
            gcs_blob_name=gcs_blob_name,
            workspace=workspace,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# --- Video Processing Endpoints ---


@app.post("/split-video/", tags=["Video Processing"], status_code=202)
async def split_video_endpoint(request: SplitRequest, background_tasks: BackgroundTasks):
    return _queue_background_job(background_tasks, task_service.process_splitting, request)
@app.post("/join-videos/", tags=["Video Processing"], status_code=202)
async def join_videos_endpoint(request: JoinRequest, background_tasks: BackgroundTasks):
    """
    Queues a background job to join multiple video clips into a single video.
    The transformation logic is now handled within the background task itself.
    """
    return _queue_background_job(background_tasks, task_service.process_joining, request)


@app.delete("/delete-gcs-blob/", tags=["GCS"], status_code=200)
async def delete_gcs_blob_endpoint(request: GCSDeleteRequest):
    """Deletes a single blob from GCS."""
    try:
        success, error = gcs_service.delete_gcs_blob(request.gcs_bucket, request.blob_name)
        if not success:
            raise HTTPException(status_code=404, detail=error)
        return {"message": f"Blob '{request.blob_name}' deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gcs/delete-batch", tags=["GCS"], status_code=200)
async def delete_gcs_blob_batch_endpoint(request: GCSBatchDeleteRequest):
    """Deletes multiple blobs from GCS in a single batch."""
    try:
        success, error = gcs_service.delete_gcs_blobs_batch(request.gcs_bucket, request.blob_names)
        if not success:
            raise HTTPException(status_code=500, detail=error)
        return {"message": f"Batch deletion successful for bucket '{request.gcs_bucket}'."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gcs/signed-url", tags=["GCS"])
async def get_signed_url_endpoint(gcs_bucket: str = Query(None), blob_name: str = Query(None)):
    """Generates a signed URL for a GCS blob."""
    try:
        url, error = gcs_service.generate_signed_url(gcs_bucket, blob_name)
        if error:
            raise HTTPException(status_code=404, detail=error)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gcs/download/{blob_name:path}", tags=["GCS"])
async def download_gcs_file_endpoint(gcs_bucket: str, blob_name: str):
    """Downloads a file from GCS and returns its content."""
    # This is a simplified example. In a real-world scenario, you would
    # stream the response or handle large files more carefully.
    from fastapi.responses import Response
    import io

    storage_client = gcs_service.get_storage_client()
    bucket = storage_client.bucket(gcs_bucket)
    blob = bucket.blob(blob_name)

    if not blob.exists():
        raise HTTPException(status_code=404, detail="File not found in GCS.")

    try:
        # Download the file's content into a BytesIO buffer
        file_buffer = io.BytesIO()
        blob.download_to_file(file_buffer)
        file_buffer.seek(0)  # Rewind the buffer to the beginning

        # Determine the content type (optional but good practice)
        content_type = blob.content_type or "application/octet-stream"

        return Response(content=file_buffer.read(), media_type=content_type)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download file: {e}")


@app.post("/generate-metadata/", tags=["AI Processing"], status_code=202)
async def generate_metadata_endpoint(request: MetadataRequest, background_tasks: BackgroundTasks):
    return _queue_background_job(background_tasks, task_service.process_metadata_generation, request)


@app.post("/generate-clips/", tags=["Video Processing"], status_code=202)
async def generate_clips_endpoint(request: ClipGenerationRequest, background_tasks: BackgroundTasks):
    return _queue_background_job(background_tasks, task_service.process_clip_generation, request)


@app.post("/generate-clips-by-face/", tags=["Video Processing"], status_code=202)
async def generate_clips_by_face_endpoint(request: FaceClipGenerationRequest, background_tasks: BackgroundTasks):
    return _queue_background_job(background_tasks, task_service.process_face_clip_generation, request)
