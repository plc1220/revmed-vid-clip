import os
import ffmpeg
import tempfile
from typing import List, Tuple
import logging
from google.cloud.video import transcoder_v1
from google.cloud.video.transcoder_v1.services.transcoder_service import (
    TranscoderServiceClient,
)


def get_video_duration(video_path: str) -> Tuple[float, str]:
    """
    Gets the duration of a video file in seconds using ffmpeg-python.
    Returns a tuple of (duration_in_seconds, error_message_string).
    """
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe["format"]["duration"])
        if duration < 0:
            return 0.0, "FFprobe reported a negative duration."
        return duration, ""
    except ffmpeg.Error as e:
        error_msg = f"Error getting duration for {os.path.basename(video_path)} with ffprobe. stderr: {e.stderr.decode('utf8')}"
        logging.error(error_msg)
        return 0.0, error_msg
    except (ValueError, KeyError) as e:
        error_msg = f"Error parsing ffprobe duration output for {os.path.basename(video_path)}: {e}."
        logging.error(error_msg)
        return 0.0, error_msg
    except Exception as e:
        error_msg = (
            f"Unexpected error getting duration for {os.path.basename(video_path)}: {e}"
        )
        logging.error(error_msg)
        return 0.0, error_msg

import gcs_service

def get_video_duration_from_gcs(bucket_name: str, blob_name: str) -> Tuple[float, str]:
    """
    Gets the duration of a video in GCS by reading only the beginning of the file.
    This avoids downloading the entire video file.
    """
    try:
        storage_client = gcs_service.get_storage_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Download the first 1MB of the file, which should contain the header
        # for most video formats.
        video_header_bytes = blob.download_as_bytes(start=0, end=1024 * 1024)

        # Use a temporary file to pass the header to ffprobe
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(video_header_bytes)
            tmp.flush()  # Ensure all data is written to the file
            return get_video_duration(tmp.name)

    except Exception as e:
        error_msg = f"Unexpected error getting duration from GCS for gs://{bucket_name}/{blob_name}: {e}"
        logging.error(error_msg)
        return 0.0, error_msg

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

# Keeping this part in case we want the fade effect in the future.
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
