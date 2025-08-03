import os
import sys
import json
import importlib
from api.main import _write_job, SplitRequest, TEMP_STORAGE_PATH
from services import gcs_service, video_service
import shutil

if __name__ == "__main__":
    job_id = sys.argv[1]
    request_data = json.loads(sys.argv[2])
    request = SplitRequest(**request_data)
    # This is a simplified version of the process_splitting function,
    # adapted to run in a separate process.
    _write_job(job_id, {"status": "in_progress", "details": "Starting video split process."})
    print(f"Job {job_id}: Starting video split process.")
    
    job_temp_dir = os.path.join(TEMP_STORAGE_PATH, job_id)
    os.makedirs(job_temp_dir, exist_ok=True)
    
    try:
        _write_job(job_id, {"status": "in_progress", "details": f"Downloading gs://{request.gcs_bucket}/{request.gcs_blob_name}..."})
        print(f"Job {job_id}: Downloading gs://{request.gcs_bucket}/{request.gcs_blob_name}...")
        local_video_path = os.path.join(job_temp_dir, os.path.basename(request.gcs_blob_name))
        success, error = gcs_service.download_gcs_blob(request.gcs_bucket, request.gcs_blob_name, local_video_path)
        if not success:
            raise Exception(f"GCS Download failed: {error}")

        _write_job(job_id, {"status": "in_progress", "details": "Splitting video into segments..."})
        print(f"Job {job_id}: Splitting video into segments...")
        split_output_dir = os.path.join(job_temp_dir, "split_output")
        os.makedirs(split_output_dir, exist_ok=True)
        
        segment_paths, error = video_service.split_video(local_video_path, request.segment_duration, split_output_dir)
        if error:
            _write_job(job_id, {"status": "in_progress", "details": f"Splitting partially failed: {error}. Uploading successful segments."})
        
        if not segment_paths:
            raise Exception("Video splitting produced no segments.")

        _write_job(job_id, {"status": "in_progress", "details": f"Uploading {len(segment_paths)} segments to GCS..."})
        print(f"Job {job_id}: Uploading {len(segment_paths)} segments to GCS...")
        output_prefix = os.path.splitext(request.gcs_blob_name)[0] + "_segments/"
        
        for i, segment_path in enumerate(segment_paths):
            segment_blob_name = os.path.join(output_prefix, os.path.basename(segment_path))
            _write_job(job_id, {"status": "in_progress", "details": f"Uploading segment {i+1}/{len(segment_paths)}: {segment_blob_name}"})
            print(f"Job {job_id}: Uploading segment {i+1}/{len(segment_paths)}: {segment_blob_name}")
            success, upload_error = gcs_service.upload_gcs_blob(request.gcs_bucket, segment_path, segment_blob_name)
            if not success:
                print(f"Warning: Failed to upload {segment_path}: {upload_error}")

        _write_job(job_id, {"status": "completed", "details": f"Successfully split video into {len(segment_paths)} segments in gs://{request.gcs_bucket}/{output_prefix}"})
        print(f"Job {job_id}: Successfully split video into {len(segment_paths)} segments in gs://{request.gcs_bucket}/{output_prefix}")

    except Exception as e:
        _write_job(job_id, {"status": "failed", "details": str(e)})
        print(f"Job {job_id}: Failed - {str(e)}")
    finally:
        if os.path.exists(job_temp_dir):
            shutil.rmtree(job_temp_dir)