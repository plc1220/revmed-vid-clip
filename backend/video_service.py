import os
import math
import io
import ffmpeg
import subprocess
import shutil
import tempfile
import uuid
from typing import List, Tuple
import logging
from google.cloud.video import transcoder_v1
from google.cloud.video.transcoder_v1.services.transcoder_service import (
    TranscoderServiceClient,
)


def get_video_duration(video_path: str) -> Tuple[float, str]:
    """
    Gets the duration of a video file in seconds using ffprobe.
    Returns a tuple of (duration_in_seconds, error_message_string).
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        duration_seconds = float(result.stdout.strip())
        if duration_seconds < 0:
            return 0.0, "FFprobe reported a negative duration."
        return duration_seconds, ""
    except FileNotFoundError:
        error_msg = "`ffprobe` command not found. Ensure FFmpeg is installed and in the system's PATH."
        logging.error(f"ERROR: {error_msg}")
        return 0.0, error_msg
    except subprocess.CalledProcessError as e:
        error_msg = f"Error getting duration for {os.path.basename(video_path)} with ffprobe. stderr: {e.stderr}"
        logging.error(error_msg)
        return 0.0, error_msg
    except ValueError as e:
        error_msg = f"Error parsing ffprobe duration output for {os.path.basename(video_path)}: {e}."
        logging.error(error_msg)
        return 0.0, error_msg
    except Exception as e:
        error_msg = f"Unexpected error getting duration for {os.path.basename(video_path)}: {e}"
        logging.error(error_msg)
        return 0.0, error_msg


def split_video(video_path: str, segment_duration_seconds: int, output_dir: str) -> Tuple[List[str], str]:
    """
    Splits a video into segments of a specified duration.
    Returns a tuple of (list_of_output_paths, error_message_string).
    """
    # If the video path is a URL, we don't check for existence on the local filesystem.
    is_url = video_path.startswith("http://") or video_path.startswith("https://")
    if not is_url and not os.path.exists(video_path):
        return [], f"Video file not found: {video_path}"

    os.makedirs(output_dir, exist_ok=True)

    total_duration, err = get_video_duration(video_path)
    if err:
        return [], f"Could not get video duration: {err}"

    if total_duration <= 0:
        return [], f"Video '{os.path.basename(video_path)}' has zero or negative duration. Cannot split."

    num_segments = math.ceil(total_duration / segment_duration_seconds)
    saved_segment_paths = []
    # Sanitize the base name to remove query parameters from URLs
    base_name_full = os.path.basename(video_path)
    base_name_sanitized = base_name_full.split("?")[0]
    base_name, ext = os.path.splitext(base_name_sanitized)

    for i in range(num_segments):
        start_time = i * segment_duration_seconds
        current_segment_duration = min(segment_duration_seconds, total_duration - start_time)

        if current_segment_duration <= 0:
            continue

        segment_file_name = f"{base_name}_part_{i+1:03d}{ext}"
        output_path = os.path.join(output_dir, segment_file_name)

        logging.info(
            f"  [Segment {i+1}/{num_segments}] Start: {start_time}s, Duration: {current_segment_duration:.2f}s, Output: {output_path}"
        )
        try:
            logging.info(f"    > Attempting to split with codec 'copy'...")
            (
                ffmpeg.input(video_path, ss=start_time, t=current_segment_duration)
                .output(output_path, c="copy", avoid_negative_ts=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logging.info(f"    > Successfully split with codec 'copy'.")
            saved_segment_paths.append(output_path)
        except ffmpeg.Error as e:
            # If 'copy' codec fails, try re-encoding
            logging.warning(f"    > Codec 'copy' failed for segment {i+1}. Trying re-encoding.")
            logging.warning(f"    > FFmpeg error (copy): {e.stderr.decode('utf8')}")
            try:
                logging.info(f"    > Attempting to split with re-encoding (libx264/aac)...")
                (
                    ffmpeg.input(video_path, ss=start_time, t=current_segment_duration)
                    .output(output_path, vcodec="libx264", acodec="aac", strict="experimental", avoid_negative_ts=1)
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                logging.info(f"    > Successfully split with re-encoding.")
                saved_segment_paths.append(output_path)
            except ffmpeg.Error as e2:
                error_msg = f"Error splitting segment {i+1} (re-encode): {e2.stderr.decode('utf8')}"
                logging.error(f"    > FATAL: Re-encoding also failed.")
                logging.error(error_msg)
                return saved_segment_paths, error_msg  # Return partial success and the error

    return saved_segment_paths, ""

def split_video_stream(video_path: str, segment_duration_seconds: int):
    """
    Splits a video from a URL into segments and yields them as in-memory bytes.
    This is a generator function.
    """
    total_duration, err = get_video_duration(video_path)
    if err:
        raise RuntimeError(f"Could not get video duration: {err}")

    if total_duration <= 0:
        logging.warning(f"Video '{os.path.basename(video_path)}' has zero or negative duration. Cannot split.")
        return

    num_segments = math.ceil(total_duration / segment_duration_seconds)
    base_name_full = os.path.basename(video_path)
    base_name_sanitized = base_name_full.split("?")[0]
    base_name, ext = os.path.splitext(base_name_sanitized)

    for i in range(num_segments):
        start_time = i * segment_duration_seconds
        current_segment_duration = min(segment_duration_seconds, total_duration - start_time)

        if current_segment_duration <= 0:
            continue

        segment_file_name = f"{base_name}_part_{i+1:03d}{ext}"
        logging.info(
            f"  [Segment {i+1}/{num_segments}] Start: {start_time}s, Duration: {current_segment_duration:.2f}s"
        )
        
        try:
            # Process the video segment in memory
            process = (
                ffmpeg.input(video_path, ss=start_time, t=current_segment_duration)
                .output('pipe:', format='mp4', movflags='frag_keyframe+empty_moov', c='copy', avoid_negative_ts=1)
                .run_async(pipe_stdout=True, pipe_stderr=True)
            )
            
            out_bytes, err_bytes = process.communicate()

            if process.returncode != 0:
                # If copy fails, try re-encoding
                logging.warning(f"    > Codec 'copy' failed for segment {i+1}. Trying re-encoding. Error: {err_bytes.decode('utf8')}")
                process = (
                    ffmpeg.input(video_path, ss=start_time, t=current_segment_duration)
                    .output('pipe:', format='mp4', movflags='frag_keyframe+empty_moov', vcodec="libx264", acodec="aac", strict="experimental", avoid_negative_ts=1)
                    .run_async(pipe_stdout=True, pipe_stderr=True)
                )
                out_bytes, err_bytes = process.communicate()

                if process.returncode != 0:
                    raise ffmpeg.Error("ffmpeg", out_bytes, err_bytes)

            # Yield the segment filename and the in-memory bytes
            yield segment_file_name, io.BytesIO(out_bytes)

        except ffmpeg.Error as e:
            error_msg = f"Error splitting segment {i+1} into stream: {e.stderr.decode('utf8')}"
            logging.error(error_msg)
            # We can choose to stop or continue. For now, we stop.
            raise RuntimeError(error_msg)


def create_clip(
    source_video_path: str, output_clip_path: str, start_seconds: float, end_seconds: float
) -> Tuple[bool, str]:
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
            ffmpeg.input(source_video_path, ss=start_seconds, t=duration)
            .output(
                output_clip_path,
                vcodec="libx264",
                acodec="aac",
                strict="experimental",
                preset="medium",
                crf=23,
                movflags="+faststart",
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True, ""
    except ffmpeg.Error as e:
        error_msg = f"FFmpeg error creating clip {os.path.basename(output_clip_path)}: {e.stderr.decode('utf8')}"
        logging.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred creating clip {os.path.basename(output_clip_path)}: {e}"
        logging.error(error_msg)
        return False, error_msg


# def _has_audio_stream(video_path: str) -> bool:
#     """Checks if a video file has an audio stream using ffprobe."""
#     try:
#         result = subprocess.run(
#             [
#                 "ffprobe",
#                 "-v",
#                 "error",
#                 "-select_streams",
#                 "a",
#                 "-show_entries",
#                 "stream=codec_type",
#                 "-of",
#                 "default=noprint_wrappers=1:nokey=1",
#                 video_path,
#             ],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.PIPE,
#             check=True,
#             text=True,
#         )
#         return "audio" in result.stdout.strip()
#     except (subprocess.CalledProcessError, FileNotFoundError):
#         return False


# def join_videos(clip_paths: List[str], output_path: str, fade_duration: float = 0.5) -> Tuple[bool, str]:
#     if not clip_paths:
#         return False, "No clip paths provided for joining."
#
#     temp_dir = tempfile.mkdtemp()
#     faded_clips = []
#     try:
#         # --- Step 1: Pre-process each clip (fade and ensure audio) ---
#         for i, clip_path in enumerate(clip_paths):
#             faded_clip_path = os.path.join(temp_dir, f"faded_{i}.mp4")
#
#             duration, err = get_video_duration(clip_path)
#             if err:
#                 logging.warning(f"Could not get duration for {clip_path}, skipping fade. Error: {err}")
#                 # Just copy the file to the temp dir to be used in the next step
#                 shutil.copy(clip_path, faded_clip_path)
#                 faded_clips.append(faded_clip_path)
#                 continue
#
#             fade_out_start = max(0, duration - fade_duration)
#
#             # Build filter complex for video and audio fades
#             video_fade = f"fade=t=in:st=0:d={fade_duration},fade=t=out:st={fade_out_start}:d={fade_duration}"
#
#             if _has_audio_stream(clip_path):
#                 audio_fade = f"afade=t=in:st=0:d={fade_duration},afade=t=out:st={fade_out_start}:d={fade_duration}"
#                 filter_complex = f"[0:v]{video_fade}[v];[0:a]{audio_fade}[a]"
#                 map_args = ["-map", "[v]", "-map", "[a]"]
#             else:
#                 # If no audio, create a silent audio track to avoid concat errors
#                 filter_complex = f"[0:v]{video_fade}[v];anullsrc=channel_layout=stereo:sample_rate=44100[a]"
#                 map_args = ["-map", "[v]", "-map", "[a]"]
#
#             cmd = [
#                 "ffmpeg", "-y", "-i", clip_path,
#                 "-filter_complex", filter_complex,
#                 *map_args,
#                 "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
#                 faded_clip_path
#             ]
#             subprocess.run(cmd, check=True, capture_output=True, text=True)
#             faded_clips.append(faded_clip_path)
#
#         # --- Step 2: Concatenate all processed clips ---
#         n = len(faded_clips)
#         streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
#         concat_filter = f"{streams}concat=n={n}:v=1:a=1[outv][outa]"
#
#         concat_cmd = ["ffmpeg", "-y"]
#         for clip in faded_clips:
#             concat_cmd.extend(["-i", clip])
#
#         concat_cmd.extend([
#             "-filter_complex", concat_filter,
#             "-map", "[outv]", "-map", "[outa]",
#             output_path
#         ])
#
#         subprocess.run(concat_cmd, check=True, capture_output=True, text=True)
#
#         return True, ""
#
#     except subprocess.CalledProcessError as e:
#         error_msg = f"FFmpeg error during video joining: {e.stderr}"
#         logging.error(error_msg)
#         return False, error_msg
#     except Exception as e:
#         error_msg = f"An unexpected error occurred during video joining: {e}"
#         logging.error(error_msg)
#         return False, error_msg
#     finally:
#         # --- Step 3: Cleanup ---
#         if os.path.exists(temp_dir):
#             shutil.rmtree(temp_dir)

def join_videos_transcoder(
    project_id: str,
    location: str,
    clip_uris: List[str],
    output_uri: str,
) -> Tuple[str, str]:
    """
    Joins multiple video clips from GCS URIs into a single video file using the Transcoder API.

    Args:
        project_id (str): The GCP project ID.
        location (str): The GCP location for the Transcoder job.
        clip_uris (List[str]): A list of GCS URIs for the video clips to be joined.
        output_uri (str): The GCS URI for the output video file.

    Returns:
        A tuple of (job_name, error_message).
    """
    if not clip_uris:
        return "", "No clip URIs provided for joining."

    try:
        client = TranscoderServiceClient()
        parent = f"projects/{project_id}/locations/{location}"

        inputs = [
            transcoder_v1.types.Input(key=f"input{i}", uri=uri)
            for i, uri in enumerate(clip_uris)
        ]

        edit_list = [
            transcoder_v1.types.EditAtom(
                key=f"atom{i}",
                inputs=[f"input{i}"],
            )
            for i in range(len(clip_uris))
        ]

        job = transcoder_v1.types.Job()
        job.config = transcoder_v1.types.JobConfig(
            inputs=inputs,
            edit_list=edit_list,
            elementary_streams=[
                transcoder_v1.types.ElementaryStream(
                    key="video-stream0",
                    video_stream=transcoder_v1.types.VideoStream(
                        h264=transcoder_v1.types.VideoStream.H264CodecSettings(
                            height_pixels=720,
                            width_pixels=1280,
                            bitrate_bps=2500000,
                            frame_rate=30,
                        ),
                    ),
                ),
                transcoder_v1.types.ElementaryStream(
                    key="audio-stream0",
                    audio_stream=transcoder_v1.types.AudioStream(
                        codec="aac", bitrate_bps=128000
                    ),
                ),
            ],
            mux_streams=[
                transcoder_v1.types.MuxStream(
                    key="sd",
                    container="mp4",
                    elementary_streams=["video-stream0", "audio-stream0"],
                ),
            ],
            output=transcoder_v1.types.Output(uri=output_uri),
        )

        response = client.create_job(parent=parent, job=job)
        logging.info(f"Transcoder job created: {response.name}")
        return response.name, ""

    except Exception as e:
        error_msg = f"An unexpected error occurred during video joining with Transcoder API: {e}"
        logging.error(error_msg)
        return "", error_msg
