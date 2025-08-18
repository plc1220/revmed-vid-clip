import os
import math
import ffmpeg
import subprocess
import tempfile
import uuid
from typing import List, Tuple
from gcs_service import download_gcs_blob_chunk

def get_video_duration(video_path: str) -> Tuple[float, str]:
    """
    Gets the duration of a video file in seconds using ffprobe.
    For GCS paths, it downloads a small chunk to a temporary file to avoid gcsfuse issues.
    Returns a tuple of (duration_in_seconds, error_message_string).
    """
    temp_file = None
    try:
        probe_path = video_path
        # If the path is a GCS FUSE path, download a chunk to a temp file
        if video_path.startswith("/gcs/"):
            parts = video_path.split('/')
            bucket_name = parts[2]
            blob_name = '/'.join(parts[3:])
            
            # Create a temporary file to download the chunk
            temp_fd, temp_file = tempfile.mkstemp(suffix=os.path.splitext(video_path)[1])
            os.close(temp_fd)
            
            # Download the first 5MB, which is usually enough for metadata
            chunk_size = 5 * 1024 * 1024
            success, err = download_gcs_blob_chunk(bucket_name, blob_name, temp_file, chunk_size)
            if not success:
                return 0.0, f"Failed to download video chunk: {err}"
            probe_path = temp_file

        # Use ffmpeg-python's probe method on the local (or chunked) file
        probe = ffmpeg.probe(probe_path)
        duration = float(probe['format']['duration'])
        
        if duration < 0:
            return 0.0, "FFprobe reported a negative duration."
        return duration, ""

    except ffmpeg.Error as e:
        error_msg = f"Error getting duration for {os.path.basename(video_path)} with ffprobe. stderr: {e.stderr.decode('utf8')}"
        print(error_msg)
        return 0.0, error_msg
    except (KeyError, ValueError) as e:
        error_msg = f"Error parsing ffprobe duration output for {os.path.basename(video_path)}: {e}."
        print(error_msg)
        return 0.0, error_msg
    except Exception as e:
        error_msg = f"Unexpected error getting duration for {os.path.basename(video_path)}: {e}"
        print(error_msg)
        return 0.0, error_msg
    finally:
        # Clean up the temporary file if it was created
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)

def split_video(video_path: str, segment_duration_seconds: int, output_dir: str) -> Tuple[List[str], str]:
    """
    Splits a video into segments of a specified duration.
    Returns a tuple of (list_of_output_paths, error_message_string).
    """
    if not os.path.exists(video_path):
        return [], f"Video file not found: {video_path}"

    os.makedirs(output_dir, exist_ok=True)
    
    total_duration, err = get_video_duration(video_path)
    if err:
        return [], f"Could not get video duration: {err}"

    if total_duration <= 0:
        return [], f"Video '{os.path.basename(video_path)}' has zero or negative duration. Cannot split."

    num_segments = math.ceil(total_duration / segment_duration_seconds)
    saved_segment_paths = []
    base_name, ext = os.path.splitext(os.path.basename(video_path))

    for i in range(num_segments):
        start_time = i * segment_duration_seconds
        current_segment_duration = min(segment_duration_seconds, total_duration - start_time)

        if current_segment_duration <= 0:
            continue

        segment_file_name = f"{base_name}_part_{i+1:03d}{ext}"
        output_path = os.path.join(output_dir, segment_file_name)

        print(f"  [Segment {i+1}/{num_segments}] Start: {start_time}s, Duration: {current_segment_duration:.2f}s, Output: {output_path}", flush=True)
        try:
            print(f"    > Attempting to split with codec 'copy'...", flush=True)
            (
                ffmpeg
                .input(video_path, ss=start_time, t=current_segment_duration)
                .output(output_path, c='copy', avoid_negative_ts=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            print(f"    > Successfully split with codec 'copy'.", flush=True)
            saved_segment_paths.append(output_path)
        except ffmpeg.Error as e:
            # If 'copy' codec fails, try re-encoding
            print(f"    > Codec 'copy' failed for segment {i+1}. Trying re-encoding.", flush=True)
            print(f"    > FFmpeg error (copy): {e.stderr.decode('utf8')}", flush=True)
            try:
                print(f"    > Attempting to split with re-encoding (libx264/aac)...", flush=True)
                (
                    ffmpeg
                    .input(video_path, ss=start_time, t=current_segment_duration)
                    .output(output_path, vcodec='libx264', acodec='aac', strict='experimental', avoid_negative_ts=1)
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                print(f"    > Successfully split with re-encoding.", flush=True)
                saved_segment_paths.append(output_path)
            except ffmpeg.Error as e2:
                error_msg = f"Error splitting segment {i+1} (re-encode): {e2.stderr.decode('utf8')}"
                print(f"    > FATAL: Re-encoding also failed.", flush=True)
                print(error_msg, flush=True)
                return saved_segment_paths, error_msg # Return partial success and the error
    
    return saved_segment_paths, ""


def create_clip(source_video_path: str, output_clip_path: str, start_seconds: float, end_seconds: float) -> Tuple[bool, str]:
    """
    Creates a single clip from a source video file.
    Returns a tuple of (success_boolean, error_message_string).
    """
    duration = end_seconds - start_seconds
    if duration <= 0:
        return False, "Clip duration must be positive."

    try:
        output_dir = os.path.dirname(output_clip_path)
        os.makedirs(output_dir, exist_ok=True)

        (
            ffmpeg
            .input(source_video_path, ss=start_seconds, t=duration)
            .output(output_clip_path, vcodec='libx264', acodec='aac', strict='experimental', preset='medium', crf=23, movflags='+faststart')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True, ""
    except ffmpeg.Error as e:
        error_msg = f"FFmpeg error creating clip {os.path.basename(output_clip_path)}: {e.stderr.decode('utf8')}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred creating clip {os.path.basename(output_clip_path)}: {e}"
        print(error_msg)
        return False, error_msg


def join_videos(clip_paths: List[str], output_path: str, fade_duration: float = 0.5) -> Tuple[bool, str]:
    """
    Joins a list of video files into a single video using the concat demuxer method,
    which is more robust. A fade-out effect is applied to each clip.
    Returns a tuple of (success_boolean, error_message_string).
    """
    if not clip_paths:
        return False, "No clip paths provided for joining."

    temp_dir = None
    try:
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)
        temp_dir = tempfile.mkdtemp()

        # 1. Create intermediate clips with fade-out
        intermediate_clips = []
        for i, clip_path in enumerate(clip_paths):
            duration, err = get_video_duration(clip_path)
            if err:
                print(f"Warning: Could not get duration for {clip_path}, skipping. Error: {err}")
                continue

            # Create a temporary path for the faded clip
            temp_faded_path = os.path.join(temp_dir, f"faded_{i}.ts")
            
            # Apply fade out to both video and audio
            fade_start = max(0, duration - fade_duration)
            
            try:
                (
                    ffmpeg
                    .input(clip_path)
                    .output(
                        temp_faded_path,
                        vf=f'fade=t=out:st={fade_start}:d={fade_duration}',
                        af=f'afade=t=out:st={fade_start}:d={fade_duration}',
                        vcodec='libx264',
                        acodec='aac',
                        # Use MPEG-TS format for concatenation
                        f='mpegts'
                    )
                    .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
                )
                intermediate_clips.append(temp_faded_path)
            except ffmpeg.Error as e:
                print(f"Error applying fade to {os.path.basename(clip_path)}, skipping this clip. FFmpeg: {e.stderr.decode('utf8')}")

        if not intermediate_clips:
            return False, "No clips could be processed for joining."

        # 2. Use the concat protocol to join the intermediate files
        # This is more robust than the concat filter
        concat_input = "concat:" + "|".join(intermediate_clips)
        
        (
            ffmpeg
            .input(concat_input, f='mpegts', c='copy')
            .output(output_path, vcodec='libx264', acodec='aac', strict='experimental')
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )

        return True, ""
    except ffmpeg.Error as e:
        error_msg = f"Error during ffmpeg video joining: {e.stderr.decode('utf8')}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred during video joining: {e}"
        print(error_msg)
        return False, error_msg
    finally:
        # Cleanup temporary directory
        if temp_dir and os.path.exists(temp_dir):
            for f in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, f))
            os.rmdir(temp_dir)