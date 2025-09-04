import json
import os
import math
import logging
import shutil
from dotenv import load_dotenv
import requests

# Import Google Cloud clients
from google.cloud.video.transcoder_v1.services.transcoder_service import TranscoderServiceClient
from google.cloud import tasks_v2

# Import services
import gcs_service
import video_service
import ai_service

# Import schemas
from schemas import (
    FaceClipGenerationRequest,
    SplitRequest,
    MetadataRequest,
    ClipGenerationRequest,
    JoinRequest,
)

load_dotenv()

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
                return None
        return data
    except (IOError, json.JSONDecodeError):
        return None

def _write_job(job_id: str, job_data: dict):
    job_path = _get_job_path(job_id)
    with open(job_path, "w") as f:
        json.dump(job_data, f)

# --- Temporary Storage Configuration ---
TEMP_STORAGE_PATH = "./api_temp_storage"
os.makedirs(TEMP_STORAGE_PATH, exist_ok=True)

# --- Cloud Tasks Helper ---
def create_face_recognition_task(request_data: dict, job_id: str) -> str:
    """
    Creates a Google Cloud Task to trigger the face recognition Cloud Run Job.
    """
    client = tasks_v2.CloudTasksClient()

    # Get configuration from environment variables
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ["GOOGLE_CLOUD_LOCATION"]
    queue = os.environ["FACE_RECOGNITION_QUEUE"]
    job_url = os.environ["FACE_RECOGNITION_JOB_URL"]
    service_account_email = os.environ["CLOUD_TASKS_SERVICE_ACCOUNT"]

    parent = client.queue_path(project, location, queue)

    gcs_cast_photo_uris = request_data.get("gcs_cast_photo_uris", [])
    
    # Construct the HTTP request for the task.
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": job_url,
            "headers": {"Content-type": "application/json"},
            "oauth_token": {"service_account_email": service_account_email},
            "body": json.dumps({
                "overrides": {
                    "container_overrides": [
                        {
                            "env": [
                                {"name": "GCS_BUCKET", "value": request_data["gcs_bucket"]},
                                {"name": "GCS_VIDEO_URI", "value": request_data["gcs_video_uri"]},
                                {"name": "GCS_CAST_PHOTO_URIS", "value": ",".join(gcs_cast_photo_uris)},
                                {"name": "JOB_ID", "value": job_id},
                            ]
                        }
                    ]
                }
            }).encode()
        }
    }

    response = client.create_task(parent=parent, task=task)
    logging.info(f"Created Cloud Task: {response.name}")
    return response.name

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

def process_splitting(job_id: str, request: SplitRequest):
    """
    Updated video splitting process using Google Cloud Video Transcoder API.
    This creates separate transcoder jobs for each segment due to API limitations.
    """
    from google.cloud.video import transcoder_v1
    
    _write_job(job_id, {"status": "in_progress", "details": "Starting video split process."})
    logging.info(f"Job {job_id}: Starting video split process using Transcoder API.")

    try:
        # Initialize Transcoder client
        transcoder_client = TranscoderServiceClient()
        project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ["GOOGLE_CLOUD_LOCATION"]  # Should match your GCS bucket region
        parent = f"projects/{project_id}/locations/{location}"

        # 1. Prepare GCS URIs
        input_uri = f"gs://{request.gcs_bucket}/{request.gcs_blob_name}"
        base_filename = os.path.basename(request.gcs_blob_name)
        base_name, ext = os.path.splitext(base_filename)
        
        _write_job(job_id, {"status": "in_progress", "details": f"Processing {input_uri}..."})
        logging.info(f"Job {job_id}: Processing {input_uri}")

        # 2. Get video duration using your existing function
        signed_url, url_error = gcs_service.generate_signed_url(request.gcs_bucket, request.gcs_blob_name)
        if url_error:
            raise Exception(f"Failed to generate signed URL for duration check: {url_error}")
        
        total_duration, duration_error = video_service.get_video_duration(signed_url)
        if duration_error or total_duration <= 0:
            raise Exception(f"Failed to get video duration: {duration_error}")

        logging.info(f"Job {job_id}: Video duration: {total_duration}s")

        # 3. Calculate segments
        num_segments = math.ceil(total_duration / request.segment_duration)
        _write_job(job_id, {"status": "in_progress", "details": f"Will create {num_segments} segments..."})
        
        # 4. Create separate transcoder jobs for each segment
        output_prefix = os.path.join(request.workspace, "segments")
        
        # Create elementary streams (reused for each job)
        elementary_streams = [
            transcoder_v1.types.ElementaryStream(
                key="video-stream0",
                video_stream=transcoder_v1.types.VideoStream(
                    h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                        bitrate_bps=2000000,
                        frame_rate=30,
                    ),
                ),
            ),
            transcoder_v1.types.ElementaryStream(
                key="audio-stream0",
                audio_stream=transcoder_v1.types.AudioStream(
                    codec="aac",
                    bitrate_bps=128000,
                ),
            ),
        ]
        
        transcoder_job_names = []
        
        for i in range(num_segments):
            start = i * request.segment_duration
            end = min(start + request.segment_duration, total_duration)
            
            # Create edit atom for this segment only
            edit_atom = transcoder_v1.types.EditAtom(
                key="atom0",  # Single atom per job
                inputs=["input0"],
                start_time_offset=f"{start:.3f}s",
                end_time_offset=f"{end:.3f}s",
            )
            
            # Create single mux stream for this segment
            segment_filename = f"{base_name}_part_{i+1:03d}.mp4"
            mux_stream = transcoder_v1.types.MuxStream(
                key="segment-output",
                file_name=segment_filename,
                container="mp4",
                elementary_streams=["video-stream0", "audio-stream0"],
            )

            # Create job config for this segment
            job_config = transcoder_v1.types.JobConfig(
                inputs=[transcoder_v1.types.Input(key="input0", uri=input_uri)],
                edit_list=[edit_atom],  # Single edit atom per job
                elementary_streams=elementary_streams,
                mux_streams=[mux_stream],  # Single mux stream per job
                output=transcoder_v1.types.Output(uri=f"gs://{request.gcs_bucket}/{output_prefix}/"),
            )
            
            # Submit individual transcoder job
            transcoder_job = transcoder_v1.types.Job(config=job_config)
            
            _write_job(job_id, {"status": "in_progress", "details": f"Submitting job for segment {i+1}/{num_segments}..."})
            logging.info(f"Job {job_id}: Submitting transcoder job for segment {i+1}")
            
            response = transcoder_client.create_job(parent=parent, job=transcoder_job)
            transcoder_job_names.append(response.name)
            
            logging.info(f"Job {job_id}: Segment {i+1} job {response.name} submitted")

        _write_job(job_id, {
            "status": "submitted",
            "details": f"{num_segments} transcoder jobs submitted. Processing segments...",
            "transcoder_job_names": transcoder_job_names,
            "num_segments": num_segments
        })
            # 7. Poll all transcoder jobs until completion
        import time
        max_wait_time = 600  # 10 minutes
        poll_interval = 30    # 30 seconds
        elapsed_time = 0
        completed_jobs = set()
        
        while elapsed_time < max_wait_time and len(completed_jobs) < len(transcoder_job_names):
            try:
                for job_name in transcoder_job_names:
                    if job_name in completed_jobs:
                        continue
                        
                    job_status = transcoder_client.get_job(name=job_name)
                    state = job_status.state.name
                    
                    if state == "SUCCEEDED":
                        completed_jobs.add(job_name)
                        logging.info(f"Job {job_id}: Segment job {job_name} completed successfully")
                        
                    elif state == "FAILED":
                        error_msg = job_status.error.message if job_status.error else "Unknown transcoder error"
                        raise Exception(f"Transcoder job {job_name} failed: {error_msg}")
                
                if len(completed_jobs) == len(transcoder_job_names):
                    final_details = f"Successfully split video into {num_segments} segments in gs://{request.gcs_bucket}/{output_prefix}/"
                    _write_job(job_id, {"status": "completed", "details": final_details})
                    logging.info(f"Job {job_id}: {final_details}")
                    return
                else:
                    progress_msg = f"Processing segments... ({len(completed_jobs)}/{len(transcoder_job_names)} completed, {elapsed_time}s elapsed)"
                    _write_job(job_id, {"status": "in_progress", "details": progress_msg})
                    logging.info(f"Job {job_id}: {progress_msg}")
                
                time.sleep(poll_interval)
                elapsed_time += poll_interval
                
            except Exception as poll_error:
                logging.error(f"Job {job_id}: Error polling transcoder status: {str(poll_error)}")
                time.sleep(poll_interval)
                elapsed_time += poll_interval
        
        # Timeout reached
        raise Exception(f"Transcoder jobs timed out after {max_wait_time} seconds")
        

    except Exception as e:
        error_msg = f"Video splitting failed: {str(e)}"
        _write_job(job_id, {"status": "failed", "details": error_msg})
        logging.error(f"Job {job_id}: {error_msg}")

# Helper function to check transcoder job status
def get_transcoder_job_status(transcoder_job_name: str) -> tuple[str, str]:
    """
    Helper function to check transcoder job status
    Returns (state, details)
    """
    try:
        transcoder_client = TranscoderServiceClient()
        job = transcoder_client.get_job(name=transcoder_job_name)
        state = job.state.name
        
        if state == "FAILED" and job.error:
            details = f"Failed: {job.error.message}"
        else:
            details = f"Status: {state}"
            
        return state, details
        
    except Exception as e:
        return "ERROR", f"Failed to check status: {str(e)}"

async def process_metadata_generation(job_id: str, request: MetadataRequest):
    """
    The actual logic for the metadata generation background task.
    This version generates one metadata JSON file per video segment.
    """
    _write_job(job_id, {"status": "in_progress", "details": "Starting metadata generation."})
    logging.info(f"Job {job_id}: Starting metadata generation for {len(request.gcs_video_uris)} videos.")

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
            logging.info(f"Job {job_id}: {details}")

            # Download the video to get its duration
            local_video_path = os.path.join(job_temp_dir, video_basename)
            success, download_error = gcs_service.download_gcs_blob(
                request.gcs_bucket, gcs_uri.split(f"gs://{request.gcs_bucket}/")[1], local_video_path
            )
            if not success:
                logging.error(
                    f"Job {job_id}: Failed to download video {gcs_uri} to get duration. Skipping. Error: {download_error}"
                )
                continue

            duration_seconds, duration_error = video_service.get_video_duration(local_video_path)
            if duration_error:
                logging.error(f"Job {job_id}: Failed to get duration for {gcs_uri}. Skipping. Error: {duration_error}")
                os.remove(local_video_path)  # Clean up
                continue

            # Format duration to HH:MM:SS
            duration_str = f"{int(duration_seconds // 3600):02d}:{int((duration_seconds % 3600) // 60):02d}:{int(duration_seconds % 60):02d}"

            prompt = request.prompt_template.replace("{{source_filename}}", video_basename)
            prompt = prompt.replace("{{actual_video_duration}}", duration_str)
            prompt = prompt.replace("{{language}}", request.language)

            metadata_json_str, error = await ai_service.generate_content_async(prompt, gcs_uri, request.ai_model_name)

            # Clean up the downloaded video file
            os.remove(local_video_path)
            if error:
                logging.error(f"Job {job_id}: Failed to generate metadata for {gcs_uri}. Error: {error}")
                continue
            if not metadata_json_str:
                logging.warning(f"Job {job_id}: No metadata generated for {gcs_uri}. Skipping.")
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
                                    start_str, end_str = timestamp.split(" - ")
                                    end_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], end_str.split(":")))
                                    if end_secs <= duration_seconds:
                                        obj["source_filename"] = gcs_uri
                                        validated_metadata.append(obj)
                                    else:
                                        logging.warning(
                                            f"Job {job_id}: Discarding invalid timestamp {timestamp} for video {gcs_uri} with duration {duration_seconds}s."
                                        )
                                except (ValueError, AttributeError):
                                    logging.warning(
                                        f"Job {job_id}: Discarding malformed timestamp '{timestamp}' for video {gcs_uri}."
                                    )
                            else:
                                logging.warning(
                                    f"Job {job_id}: Discarding metadata object with missing timestamp for video {gcs_uri}."
                                )

                if not validated_metadata:
                    logging.warning(f"Job {job_id}: No valid metadata generated for {gcs_uri} after validation. Skipping.")
                    continue

                # Even if the AI returns a list, we save it to a file specific to this video.
                output_filename = f"{os.path.splitext(video_basename)[0]}_metadata.json"
                local_metadata_path = os.path.join(job_temp_dir, output_filename)

                with open(local_metadata_path, "w") as f:
                    json.dump(validated_metadata, f, indent=2)

                # Upload the individual metadata file
                metadata_blob_name = os.path.join(request.workspace, request.gcs_output_prefix, output_filename)
                upload_details = f"Uploading metadata for {video_basename} to {metadata_blob_name}"
                _write_job(job_id, {"status": "in_progress", "details": upload_details})
                logging.info(f"Job {job_id}: {upload_details}")

                success, upload_error = gcs_service.upload_gcs_blob(
                    request.gcs_bucket, local_metadata_path, metadata_blob_name
                )
                if success:
                    processed_files_count += 1
                    generated_metadata_files.append(f"gs://{request.gcs_bucket}/{metadata_blob_name}")
                else:
                    logging.error(f"Job {job_id}: Failed to upload metadata for {video_basename}. Error: {upload_error}")

            except json.JSONDecodeError as e:
                logging.error(f"Job {job_id}: Failed to parse metadata JSON for {gcs_uri}. Error: {e}")
                continue

        if processed_files_count == 0:
            final_details = "Metadata generation finished, but no valid metadata was produced or uploaded."
        else:
            final_details = f"Successfully generated and uploaded {processed_files_count} metadata file(s)."

        _write_job(
            job_id, {"status": "completed", "details": final_details, "generated_files": generated_metadata_files}
        )
        logging.info(f"Job {job_id}: {final_details}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        logging.error(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_clip_generation(job_id: str, request: ClipGenerationRequest):
    """
    The actual logic for the clip generation background task.
    This version uses the Google Cloud Transcoder API to generate clips.
    """
    from google.cloud.video import transcoder_v1
    
    _write_job(job_id, {"status": "in_progress", "details": "Starting clip generation."})
    logging.info(f"Job {job_id}: Starting clip generation from {len(request.metadata_blob_names)} metadata file(s).")

    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)

    clips_by_source_video = {}  # Key: source_blob_name, Value: list of clip_data

    try:
        # --- Step 1: Aggregate all clips from metadata files and group by source video ---
        _write_job(job_id, {"status": "in_progress", "details": "Aggregating and grouping clips from metadata..."})
        logging.info(f"Job {job_id}: Aggregating clips from {len(request.metadata_blob_names)} metadata files.")

        for metadata_blob_name in request.metadata_blob_names:
            local_metadata_path = os.path.join(job_temp_dir, os.path.basename(metadata_blob_name))
            success, error = gcs_service.download_gcs_blob(request.gcs_bucket, metadata_blob_name, local_metadata_path)
            if not success:
                logging.error(f"Job {job_id}: Failed to download metadata {metadata_blob_name}. Skipping. Error: {error}")
                continue

            with open(local_metadata_path, "r") as f:
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

                    if source_gcs_uri.startswith(f"gs://{request.gcs_bucket}/"):
                        source_blob_name = source_gcs_uri.split(f"gs://{request.gcs_bucket}/", 1)[1]
                        if source_blob_name not in clips_by_source_video:
                            clips_by_source_video[source_blob_name] = []
                        clips_by_source_video[source_blob_name].append(clip_data)
                    else:
                        logging.warning(f"Job {job_id}: Skipping clip with invalid or mismatched GCS URI: {source_gcs_uri}")

            except (json.JSONDecodeError, ValueError) as e:
                logging.error(f"Job {job_id}: Invalid JSON in {metadata_blob_name}. Error: {e}")
                continue
        
        # --- Step 2: Initialize Transcoder client and common settings ---
        transcoder_client = TranscoderServiceClient()
        project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ["GOOGLE_CLOUD_LOCATION"]
        parent = f"projects/{project_id}/locations/{location}"

        elementary_streams = [
            transcoder_v1.types.ElementaryStream(
                key="video-stream0",
                video_stream=transcoder_v1.types.VideoStream(
                    h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                        bitrate_bps=2000000,
                        frame_rate=30,
                    ),
                ),
            ),
            transcoder_v1.types.ElementaryStream(
                key="audio-stream0",
                audio_stream=transcoder_v1.types.AudioStream(
                    codec="aac",
                    bitrate_bps=128000,
                ),
            ),
        ]

        # --- Step 3: Create and submit a transcoder job for each clip ---
        transcoder_job_names = []
        total_clips_to_generate = sum(len(c) for c in clips_by_source_video.values())
        logging.info(f"Job {job_id}: Found {total_clips_to_generate} clips to generate from {len(clips_by_source_video)} unique source videos.")
        
        processed_clips_count = 0
        for source_blob_name, clips_to_create in clips_by_source_video.items():
            input_uri = f"gs://{request.gcs_bucket}/{source_blob_name}"

            for clip_data in clips_to_create:
                time_range = clip_data.get("timestamp_start_end")
                if not time_range:
                    logging.warning(f"Job {job_id}: Skipping clip with missing 'timestamp_start_end': {clip_data}")
                    continue

                try:
                    start_str, end_str = time_range.split(" - ")
                    start_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], start_str.split(":")))
                    end_secs = sum(x * int(t) for x, t in zip([3600, 60, 1], end_str.split(":")))
                except (ValueError, AttributeError):
                    logging.warning(f"Job {job_id}: Invalid time format '{time_range}'. Skipping clip.")
                    continue

                processed_clips_count += 1
                clip_filename = f"{os.path.splitext(os.path.basename(source_blob_name))[0]}_clip_{processed_clips_count}.mp4"

                edit_atom = transcoder_v1.types.EditAtom(
                    key=f"atom-clip-{processed_clips_count}",
                    inputs=["input0"],
                    start_time_offset=f"{start_secs:.3f}s",
                    end_time_offset=f"{end_secs:.3f}s",
                )

                mux_stream = transcoder_v1.types.MuxStream(
                    key=f"mux-clip-{processed_clips_count}",
                    file_name=clip_filename,
                    container="mp4",
                    elementary_streams=["video-stream0", "audio-stream0"],
                )

                job_config = transcoder_v1.types.JobConfig(
                    inputs=[transcoder_v1.types.Input(key="input0", uri=input_uri)],
                    edit_list=[edit_atom],
                    elementary_streams=elementary_streams,
                    mux_streams=[mux_stream],
                    output=transcoder_v1.types.Output(uri=f"gs://{request.gcs_bucket}/{request.workspace}/{request.output_gcs_prefix}/"),
                )

                transcoder_job = transcoder_v1.types.Job(config=job_config)
                
                details = f"Submitting job for clip {processed_clips_count}/{total_clips_to_generate}: {clip_filename}"
                _write_job(job_id, {"status": "in_progress", "details": details})
                logging.info(f"Job {job_id}: {details}")

                response = transcoder_client.create_job(parent=parent, job=transcoder_job)
                transcoder_job_names.append(response.name)
                logging.info(f"Job {job_id}: Clip job {response.name} submitted")

        _write_job(job_id, {
            "status": "submitted",
            "details": f"{len(transcoder_job_names)} transcoder jobs submitted for clip generation.",
            "transcoder_job_names": transcoder_job_names,
            "num_clips": len(transcoder_job_names)
        })

        # --- Step 4: Poll all transcoder jobs until completion ---
        import time
        max_wait_time = 900  # 15 minutes
        poll_interval = 30   # 30 seconds
        elapsed_time = 0
        completed_jobs = set()

        while elapsed_time < max_wait_time and len(completed_jobs) < len(transcoder_job_names):
            try:
                for job_name in transcoder_job_names:
                    if job_name in completed_jobs:
                        continue
                    
                    job_status = transcoder_client.get_job(name=job_name)
                    state = job_status.state.name
                    
                    if state == "SUCCEEDED":
                        completed_jobs.add(job_name)
                        logging.info(f"Job {job_id}: Clip job {job_name} completed successfully")
                        
                    elif state == "FAILED":
                        error_msg = job_status.error.message if job_status.error else "Unknown transcoder error"
                        raise Exception(f"Transcoder job {job_name} failed: {error_msg}")
                
                if len(completed_jobs) == len(transcoder_job_names):
                    final_details = f"Successfully generated {len(transcoder_job_names)} clips."
                    _write_job(job_id, {"status": "completed", "details": final_details})
                    logging.info(f"Job {job_id}: {final_details}")
                    return
                else:
                    progress_msg = f"Processing clips... ({len(completed_jobs)}/{len(transcoder_job_names)} completed, {elapsed_time}s elapsed)"
                    _write_job(job_id, {"status": "in_progress", "details": progress_msg})
                    logging.info(f"Job {job_id}: {progress_msg}")
                
                time.sleep(poll_interval)
                elapsed_time += poll_interval
                
            except Exception as poll_error:
                logging.error(f"Job {job_id}: Error polling transcoder status: {str(poll_error)}")
                time.sleep(poll_interval)
                elapsed_time += poll_interval
        
        if len(completed_jobs) < len(transcoder_job_names):
            raise Exception(f"Clip generation timed out after {max_wait_time} seconds. {len(completed_jobs)}/{len(transcoder_job_names)} jobs completed.")
        _write_job(job_id, {"status": "completed", "details": final_details, "generated_clips": generated_clip_blob_names})
        logging.info(f"Job {job_id}: Clip generation completed.")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        logging.error(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)

def process_face_detection_and_copy(job_id: str, request: FaceClipGenerationRequest):
    """
    Orchestrates face detection by dispatching a Cloud Task.
    The actual copying logic will need to be handled differently, perhaps by another job
    or by inspecting the results of the face detection job. For now, this just dispatches the job.
    """
    _write_job(job_id, {"status": "in_progress", "details": "Dispatching face detection job."})
    logging.info(f"Job {job_id}: Dispatching face detection job for video {request.gcs_video_uri}")

    try:
        # Convert Pydantic model to dict to pass to task creator
        request_data = request.dict()
        task_name = create_face_recognition_task(request_data, job_id)
        _write_job(job_id, {
            "status": "submitted",
            "details": f"Successfully dispatched face detection job. Task: {task_name}",
            "task_name": task_name
        })
        logging.info(f"Job {job_id}: Face detection task {task_name} created.")

    except Exception as e:
        error_msg = f"Failed to dispatch face detection job: {str(e)}"
        _write_job(job_id, {"status": "failed", "details": error_msg})
        logging.error(f"Job {job_id}: {error_msg}", exc_info=True)

def process_joining(job_id: str, request: JoinRequest):
    """
    The actual logic for the video joining background task.
    This version uses the Google Cloud Transcoder API.
    """
    import uuid
    _write_job(job_id, {"status": "in_progress", "details": "Starting video joining process."})
    
    try:
        # --- Data Transformation ---
        # Convert blob names to full GCS URIs
        gcs_clip_uris = [f"gs://{request.gcs_bucket}/{blob_name}" for blob_name in request.clip_blob_names]
        logging.info(f"Job {job_id}: Starting video joining process for {len(gcs_clip_uris)} clips.")

        # Generate a unique filename for the output video
        output_filename = f"joined_video_{uuid.uuid4()}.mp4"
        
        # Construct the full GCS output URI, which must be a directory.
        output_uri = f"gs://{request.gcs_bucket}/{request.workspace}/{request.output_gcs_prefix}/"

        # --- Transcoder Job ---
        project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ["GOOGLE_CLOUD_LOCATION"]

        job_name, error = video_service.join_videos_transcoder(
            project_id=project_id,
            location=location,
            clip_uris=gcs_clip_uris,
            output_uri=output_uri,
        )

        if error:
            raise Exception(f"Failed to create transcoder job: {error}")

        _write_job(
            job_id,
            {
                "status": "submitted",
                "details": f"Transcoder job '{job_name}' submitted for joining clips.",
                "transcoder_job_name": job_name,
                "output_uri": output_uri
            },
        )
        logging.info(f"Job {job_id}: Transcoder job '{job_name}' submitted.")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        logging.error(f"Job {job_id}: Failed - {str(e)}")


