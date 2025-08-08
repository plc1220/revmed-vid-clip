import os
import math
import ffmpeg
import subprocess
import tempfile
import uuid
from typing import List, Tuple


def get_video_duration(video_path: str) -> Tuple[float, str]:
    """
    Gets the duration of a video file in seconds using ffprobe.
    Returns a tuple of (duration_in_seconds, error_message_string).
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
        )
        duration_seconds = float(result.stdout.strip())
        if duration_seconds < 0:
            return 0.0, "FFprobe reported a negative duration."
        return duration_seconds, ""
    except FileNotFoundError:
        error_msg = "`ffprobe` command not found. Ensure FFmpeg is installed and in the system's PATH."
        print(f"ERROR: {error_msg}")
        return 0.0, error_msg
    except subprocess.CalledProcessError as e:
        error_msg = f"Error getting duration for {os.path.basename(video_path)} with ffprobe. stderr: {e.stderr}"
        print(error_msg)
        return 0.0, error_msg
    except ValueError as e:
        error_msg = f"Error parsing ffprobe duration output for {os.path.basename(video_path)}: {e}."
        print(error_msg)
        return 0.0, error_msg
    except Exception as e:
        error_msg = f"Unexpected error getting duration for {os.path.basename(video_path)}: {e}"
        print(error_msg)
        return 0.0, error_msg

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


def join_videos(clip_paths: List[str], output_path: str) -> Tuple[bool, str]:
    """
    Joins a list of video files into a single video.
    Returns a tuple of (success_boolean, error_message_string).
    """
    if not clip_paths:
        return False, "No clip paths provided for joining."

    # Create a temporary file list for ffmpeg concatenation
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as tmp_list_file:
        for path in clip_paths:
            # FFmpeg requires special handling of characters in file paths
            # FFmpeg requires absolute paths to correctly locate the files.
            absolute_path = os.path.abspath(path)
            sanitized_path = absolute_path.replace("'", "'\\''")
            tmp_list_file.write(f"file '{sanitized_path}'\n")
        concat_list_filename = tmp_list_file.name

    try:
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        (
            ffmpeg
            .input(concat_list_filename, format='concat', safe=0)
            .output(output_path, c='copy', vsync='vfr')
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
        return True, ""
    except ffmpeg.Error as e:
        error_msg = f"Error during ffmpeg concatenation: {e.stderr.decode('utf8')}"
        print(error_msg)
        return False, error_msg
    finally:
        if os.path.exists(concat_list_filename):
            os.remove(concat_list_filename)