import streamlit as st
import os
import re # Import re for regular expressions
from google.cloud import storage # Added for GCS listing
from typing import Optional
import ffmpeg # For clip generation
import tempfile # For temporary directory for GCS downloads
import google.generativeai as genai
import get_model # Ensures genai is configured via get_model.py's top-level code

# Helper function to parse timecodes
def parse_timecode(timecode_str: str) -> float:
    """Converts HH:MM:SS, MM:SS, or SS string to seconds."""
    parts = list(map(int, timecode_str.split(':')))
    if len(parts) == 3:  # HH:MM:SS
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    elif len(parts) == 2:  # MM:SS
        return float(parts[0] * 60 + parts[1])
    elif len(parts) == 1:  # SS
        return float(parts[0])
    else:
        raise ValueError(f"Invalid timecode format: {timecode_str}")

def render_tab5(
    gcs_bucket_name_param: str,
    gemini_api_key_param: str, # Though genai is configured globally by app.py
    ai_model_name_param: str,
    temp_clips_output_dir_param: str,
    temp_ai_clips_individual_output_dir_param: str,
    temp_ai_video_joined_output_dir_param: str,
    gcs_processed_video_prefix_param: str,
    gcs_metadata_prefix_param: str, # Renamed from metadata_gcs_prefix for clarity
    gcs_output_clips_prefix_param: str,
    gemini_ready_param: bool
    # allowed_metadata_extensions: list = None # Future: if we want to filter by .txt, .json etc.
):
    st.header("Step 5: Generate Clips with AI")

    # Use parameters for output directories
    # clips_output_dir is not directly used for file saving in the new flow,
    # but if it were, it would be temp_clips_output_dir_param.
    # For now, we ensure the AI-specific directories exist.
    os.makedirs(temp_ai_clips_individual_output_dir_param, exist_ok=True)
    os.makedirs(temp_ai_video_joined_output_dir_param, exist_ok=True)
    # os.makedirs(temp_clips_output_dir_param, exist_ok=True) # if this specific one is still needed

    # Session state for generated clip paths
    if "generated_clips_paths_tab5" not in st.session_state:
        st.session_state.generated_clips_paths_tab5 = []
    # Note: output_clip_filename_style_tab5 is initialized in app.py, so it should be available.
    if "ai_generated_clip_list_for_processing_tab5" not in st.session_state:
        st.session_state.ai_generated_clip_list_for_processing_tab5 = ""

    # --- GCS Metadata File Listing and Selection ---
    st.subheader(f"Select Metadata File from gs://{gcs_bucket_name_param}/{gcs_metadata_prefix_param}")
    gcs_metadata_files_options = [] # Renamed to avoid conflict with a potential global var
    error_listing_metadata = None
    # metadata_gcs_prefix = "metadata/" # Now passed as gcs_metadata_prefix_param
    
    if not gcs_bucket_name_param:
        error_listing_metadata = "GCS Bucket name not provided. Please configure it in app settings."
        st.error(error_listing_metadata)
    else:
        try:
            storage_client_list = storage.Client()
            bucket_list = storage_client_list.bucket(gcs_bucket_name_param)
            
            # Fetch actual files and sort them
            actual_files = [b.name for b in bucket_list.list_blobs(prefix=gcs_metadata_prefix_param) if not b.name.endswith('/')]
            actual_files.sort()
            gcs_metadata_files_options = ["-- Select a metadata file --"] + actual_files


            if len(gcs_metadata_files_options) <= 1 : # Only placeholder exists
                st.warning(f"No metadata files found in 'gs://{gcs_bucket_name_param}/{gcs_metadata_prefix_param}'.")
            else:
                st.success(f"Found {len(gcs_metadata_files_options) - 1} metadata file(s) in 'gs://{gcs_bucket_name_param}/{gcs_metadata_prefix_param}'.")
                # Single file selection and display UI removed as per request.

        except Exception as e_list_meta:
            error_listing_metadata = f"Error listing metadata files from GCS (gs://{gcs_bucket_name_param}/{gcs_metadata_prefix_param}): {e_list_meta}"
            st.error(error_listing_metadata)

    # _parse_single_metadata_content function removed as it's no longer used.

    # --- Function to Extract All Raw GCS Metadata Content ---
    # (This function will be modified next to populate a new raw text area)
    def extract_all_clips_details(): # Function name kept, but behavior changed
        print(f"DEBUG: extract_all_clips_details (raw content extraction) called.")
        st.session_state.raw_gcs_metadata_content_tab5 = "" # Initialize/clear the new session state

        if not gcs_metadata_files_options or len(gcs_metadata_files_options) <= 1:
            st.warning("No GCS metadata files found to process.")
            return

        all_raw_content_parts = []
        files_processed_count = 0
        files_with_errors_count = 0
        
        try:
            storage_client_extract_all = storage.Client()
            bucket_extract_all = storage_client_extract_all.bucket(gcs_bucket_name_param)
        except Exception as e_client:
            st.error(f"Failed to initialize GCS client: {e_client}")
            return

        for gcs_file_path in gcs_metadata_files_options:
            if gcs_file_path == "-- Select a metadata file --":
                continue

            try:
                print(f"DEBUG: Processing file for raw content: {gcs_file_path}")
                blob_extract = bucket_extract_all.blob(gcs_file_path)
                if blob_extract.exists():
                    content_str = blob_extract.download_as_text()
                    all_raw_content_parts.append(f"# --- Content from: {gcs_file_path} ---\n{content_str}\n\n")
                    files_processed_count +=1
                else:
                    st.warning(f"GCS file not found: {gcs_file_path}")
                    files_with_errors_count += 1
            except Exception as e_gcs_download:
                st.error(f"Error downloading GCS file {gcs_file_path}: {e_gcs_download}")
                files_with_errors_count += 1
        
        if all_raw_content_parts:
            st.session_state.raw_gcs_metadata_content_tab5 = "".join(all_raw_content_parts)
            st.success(f"Successfully loaded raw content from {files_processed_count} GCS file(s). {files_with_errors_count} file(s) had errors.")
        else:
            st.warning(f"No raw content loaded from GCS files. Processed {files_processed_count} file(s). {files_with_errors_count} file(s) had errors.")
            # trailer_details_input_content_tab5 is NOT modified here anymore
            # output_clip_filename_style_tab5 is NOT modified here anymore

    # --- UI for Buttons ---
    # Condition for showing "Extract All Clips" (any GCS files available, excluding placeholder)
    show_extract_all_button = gcs_metadata_files_options and len(gcs_metadata_files_options) > 1

    if show_extract_all_button:
        if st.button("📚 Load All GCS Metadata (Raw)", key="extract_all_clips_button_tab5", help="Loads raw content from ALL metadata files listed from GCS into the text area below."):
            extract_all_clips_details()
    
    st.markdown("---")
    st.subheader("Raw GCS Metadata Content")
    st.text_area(
        "All GCS Metadata (Raw View):",
        value=st.session_state.raw_gcs_metadata_content_tab5,
        height=300,
        key="raw_gcs_metadata_textarea_tab5",
        disabled=True
    )
    st.markdown("---")
    # Input area for trailer details (e.g., from metadata files or manual input)
# New Prompt Text Area
    default_prompt_text = """**Explanation and Efficiency Improvements:**

1.  **Clear Role and Goal:** "You are an expert AI Trailer Editor. Your task is to construct a compelling and emotionally engaging 90-second (approximately 1.5 minutes) trailer sequence."
2.  **Input Definition:** Clearly states it will receive a list of JSON objects and highlights the key fields the AI should focus on for decision-making (`source_filename`, `timestamp_start_end`, `editor_note_clip_rationale`, `dominant_emotional_tone_impact`, `trailer_potential_category`, `pacing_suggestion_for_clip`). This reduces the AI's need to parse and consider less relevant fields for *this specific task*.
3.  **Trailer Objectives (Prioritized):** Lists the key elements of a good trailer, guiding the AI's selection process.
4.  **Strict Duration Adherence:** Emphasizes the ~90-second target and the need to calculate durations.
5.  **Step-by-Step Task Breakdown:**
    *   Analyze all clips.
    *   Select a sequence.
    *   Calculate individual clip durations.
    *   Ensure total duration is ~90s.
    *   Use specific fields (`trailer_potential_category`, `pacing_suggestion_for_clip`, `dominant_emotional_tone_impact`, `editor_note_clip_rationale`) to guide choices. This makes the selection process more "intelligent" rather than random.
6.  **Simplified Output Format:** The requested output is very simple (filename on one line, timestamp on the next), making it easy for the AI to generate and for you to parse. This avoids potential JSON formatting errors from the AI for this second-stage task.
7.  **Crucial Instructions & Constraints:**
    *   "Mini-story or strong thematic impression."
    *   "MUST use the `source_filename` and `timestamp_start_end` exactly as provided." (Prevents hallucination of these key details).
    *   "Do not invent new clips or timestamps."
    *   "List the selected clips in the order they should appear."
    *   "State the calculated total duration..." This forces the AI to do the math and helps you verify.
8.  **Efficiency:**
    *   By telling the AI which JSON fields are most important for *this trailer assembly task*, you're guiding its focus.
    *   The simplified output format reduces the risk of complex generation errors.
    *   The task is narrowed down to selection and sequencing from pre-processed data, which is less computationally intensive than analyzing raw video again.
    
    **Instructions & Constraints (Updated Emphasis):**
    *   The final sequence should tell a mini-story or create a strong thematic impression.
    *   You MUST use the `source_filename` and `timestamp_start_end` exactly as provided in the input JSON for the clips you select.
    *   Do not invent new clips or timestamps.
    *   List the selected clips in the order they should appear in the trailer.
    *   **Crucially, do NOT output the calculated total duration or any other summary text. Your response should ONLY contain the list of filenames and their corresponding timestamps, adhering strictly to the two-line-per-clip format.**
    *   **Your output must begin directly with the first filename and end directly with the last timestamp of the final selected clip.** No leading or trailing text whatsoever.

Now, analyze the provided clip data and generate ONLY the trailer sequence list.
"""
    st.text_area(
        "Prompt:",
        value=default_prompt_text,
        height=300,
        key="prompt_textarea_tab5"
    )
    st.markdown("---") # Separator after the new text area

    # Use a key for the widget itself to ensure its state is managed by Streamlit
    
    # os.makedirs(temp_clips_output_dir_param, exist_ok=True) # Moved to the top of render_tab5

    # Button is enabled if there are GCS metadata files to process and Gemini is ready
    generate_clips_button_disabled = not (gcs_metadata_files_options and len(gcs_metadata_files_options) > 1 and gemini_ready_param)
    if not gemini_ready_param:
        st.warning("Gemini is not ready. Please configure the API key in the sidebar.")


    if st.button("✨ Generate Clips", key="generate_clips_button_tab5", disabled=generate_clips_button_disabled):
        st.session_state.generated_clips_paths_tab5 = [] # Clear previous clips

        # 1. Ensure GCS metadata is loaded
        extract_all_clips_details() # This populates st.session_state.raw_gcs_metadata_content_tab5
        
        gcs_content = st.session_state.get("raw_gcs_metadata_content_tab5", "")
        ai_prompt = st.session_state.get("prompt_textarea_tab5", default_prompt_text) # default_prompt_text is defined in this file

        if not gcs_content.strip():
            st.error("No metadata content loaded from GCS. Cannot proceed with AI generation.")
            return
        
        if not ai_prompt.strip():
            st.error("AI Prompt is empty. Cannot proceed.") # Should use default if session state is empty
            return

        clip_details_text = ""
        st.info("Generating clip list with AI. This may take a moment...")
        try:
            # genai should be configured by app.py using get_model.py
            # Use the passed ai_model_name_param
            model = genai.GenerativeModel(ai_model_name_param)
            full_ai_prompt = f"{ai_prompt}\n\nHere is the metadata from GCS files:\n{gcs_content}"
            
            # Log the prompt being sent to the AI for debugging
            print(f"DEBUG: Sending the following prompt to Gemini:\n---\n{full_ai_prompt}\n---")
            st.expander("View Full Prompt Sent to AI").text(full_ai_prompt)

            response = model.generate_content(full_ai_prompt)
            raw_ai_output = response.text
            
            # Clean the AI output
            cleaned_lines = []
            # Remove markdown code fences and strip whitespace
            processed_text = raw_ai_output.strip()
            if processed_text.startswith("```") and processed_text.endswith("```"):
                processed_text = processed_text[3:-3].strip()
            elif processed_text.startswith("```"):
                processed_text = processed_text[3:].strip()
            elif processed_text.endswith("```"):
                processed_text = processed_text[:-3].strip()

            for line in processed_text.split('\n'):
                # Remove any summary lines like "Total calculated duration..."
                if not line.strip().lower().startswith("total calculated duration"):
                    cleaned_lines.append(line)
            
            clip_details_text = "\n".join(cleaned_lines).strip()
            st.session_state.ai_generated_clip_list_for_processing_tab5 = clip_details_text # Store for the new button
            
            st.success("AI generated clip list successfully!")
            # Stop further processing here for THIS button.
            pass # Removed return to allow UI to re-render fully
        except Exception as e_ai:
            st.error(f"Error during AI clip list generation: {e_ai}")
            # Attempt to get more details from the exception if it's a Google API error
            if hasattr(e_ai, 'message'):
                st.error(f"AI Error Message: {e_ai.message}")
            if hasattr(e_ai, 'response') and hasattr(e_ai.response, 'prompt_feedback'):
                 st.error(f"AI Prompt Feedback: {e_ai.response.prompt_feedback}")
            return
    
    # Display AI output (this will show the content from st.session_state.ai_generated_clip_list_for_processing_tab5)
    st.text_area("AI Output (for clip generation):", value=st.session_state.ai_generated_clip_list_for_processing_tab5, height=150, key="ai_output_display_area_tab5", disabled=True)

    # --- New Button: Generate AI Video ---
    st.markdown("---") # Separator
    
    ai_video_button_disabled = not bool(st.session_state.ai_generated_clip_list_for_processing_tab5.strip())
    if st.button("🎬 Generate AI Video", key="generate_ai_video_button_tab5", disabled=ai_video_button_disabled):
        clip_details_text_for_processing = st.session_state.ai_generated_clip_list_for_processing_tab5.strip()
        
        if not clip_details_text_for_processing: # Should be caught by disabled state, but double check
            st.error("AI Output is empty. Click 'Generate Clips' first to populate the list.")
            return

        # Use parameters for output directories
        # ai_clips_individual_output_dir = "./temp_ai_clip" # Now temp_ai_clips_individual_output_dir_param
        os.makedirs(temp_ai_clips_individual_output_dir_param, exist_ok=True)
        
        # ai_video_joined_output_dir = "./temp_ai_joined_video" # Now temp_ai_video_joined_output_dir_param
        os.makedirs(temp_ai_video_joined_output_dir_param, exist_ok=True)

        output_basename_style = st.session_state.output_clip_filename_style_tab5.strip() # Uses default from app.py

        if not output_basename_style: # Should always be true due to default in app.py
            st.error("Clip filename style is missing (check app.py defaults). Cannot proceed with AI video generation.")
            return

        clip_entries = clip_details_text_for_processing.split('\n')
        parsed_clip_data = []
        if len(clip_entries) >= 2:
            for i in range(0, len(clip_entries) -1, 2): # Iterate in pairs
                source_file = clip_entries[i].strip()
                timecode_str = clip_entries[i+1].strip()
                if source_file and timecode_str:
                    parsed_clip_data.append({"source": source_file, "timecode": timecode_str})
                else:
                    st.warning(f"Skipping incomplete entry: File='{source_file}', Timecode='{timecode_str}'")
        
        if not parsed_clip_data:
            st.error("No valid clip entries (source filename + timecode) found in the details.")
            return

        st.info(f"Starting actual clip generation... {len(parsed_clip_data)} clips to process.")
        
        generated_clip_paths_this_run = []
        clips_processed_successfully = 0
        clips_with_errors = 0
        
        # GCS client for downloading source videos
        try:
            gcs_client_downloader = storage.Client()
            gcs_bucket_downloader = gcs_client_downloader.bucket(gcs_bucket_name_param)
        except Exception as e_gcs_client:
            st.error(f"Failed to initialize GCS client for downloading source videos: {e_gcs_client}")
            return

        with tempfile.TemporaryDirectory(prefix="gcs_downloads_tab5_") as tmp_download_dir:
            for idx, clip_data in enumerate(parsed_clip_data):
                source_gcs_filename = clip_data['source']
                # Use gcs_processed_video_prefix_param for source videos
                source_gcs_blob_path = f"{gcs_processed_video_prefix_param}{source_gcs_filename}"
                if not gcs_processed_video_prefix_param.endswith('/'): # ensure trailing slash
                    source_gcs_blob_path = f"{gcs_processed_video_prefix_param}/{source_gcs_filename}"

                local_downloaded_source_path = os.path.join(tmp_download_dir, source_gcs_filename)
                final_clip_output_path = None # Initialize to prevent UnboundLocalError

                clip_status_message = st.empty()
                clip_status_message.info(f"Processing clip {idx+1}/{len(parsed_clip_data)}: '{source_gcs_filename}' ({clip_data['timecode']}). Downloading...")

                try:
                    # 1. Download source video from GCS
                    blob_to_download = gcs_bucket_downloader.blob(source_gcs_blob_path)
                    if not blob_to_download.exists():
                        st.error(f"Clip {idx+1}: Source video gs://{gcs_bucket_name_param}/{source_gcs_blob_path} not found.")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: GCS source not found.")
                        continue
                    
                    blob_to_download.download_to_filename(local_downloaded_source_path)
                    
                    if not os.path.exists(local_downloaded_source_path) or os.path.getsize(local_downloaded_source_path) == 0:
                        st.error(f"Clip {idx+1}: Downloaded source file '{local_downloaded_source_path}' is missing or empty.")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Downloaded file issue.")
                        continue
                    
                    clip_status_message.info(f"Clip {idx+1}: Downloaded. Probing video duration...")

                    # Probe video for duration
                    try:
                        probe = ffmpeg.probe(local_downloaded_source_path)
                        video_stream_info = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
                        if not video_stream_info or 'duration' not in video_stream_info:
                            st.error(f"Clip {idx+1}: Could not determine duration of downloaded source video '{source_gcs_filename}'.")
                            clips_with_errors += 1
                            clip_status_message.error(f"Clip {idx+1} Error: Failed to probe duration.")
                            continue
                        source_video_duration_seconds = float(video_stream_info['duration'])
                        clip_status_message.info(f"Clip {idx+1}: Source duration {source_video_duration_seconds:.2f}s. Parsing timecode '{clip_data['timecode']}'...")
                    except Exception as e_probe:
                        st.error(f"Clip {idx+1}: Error probing video '{source_gcs_filename}': {e_probe}")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Probing failed.")
                        continue

                    # 2. Parse timecodes
                    time_parts = clip_data['timecode'].split('-')
                    if len(time_parts) != 2:
                        st.error(f"Clip {idx+1}: Invalid time range format '{clip_data['timecode']}'. Expected HH:MM:SS - HH:MM:SS")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Invalid timecode format.")
                        continue
                    
                    start_time_str, end_time_str = time_parts[0].strip(), time_parts[1].strip()
                    start_seconds = parse_timecode(start_time_str) # Can raise ValueError
                    end_seconds = parse_timecode(end_time_str)   # Can raise ValueError

                    # Validate timecodes against probed duration
                    if start_seconds >= source_video_duration_seconds:
                        st.error(f"Clip {idx+1}: Start time ({start_time_str} / {start_seconds:.2f}s) is at or beyond source video duration ({source_video_duration_seconds:.2f}s).")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Start time out of bounds.")
                        continue
                    
                    if start_seconds >= end_seconds:
                        st.error(f"Clip {idx+1}: Start time ({start_time_str} / {start_seconds:.2f}s) must be before end time ({end_time_str} / {end_seconds:.2f}s).")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Start time not before end time.")
                        continue

                    # Adjust end_seconds if it exceeds video duration
                    if end_seconds > source_video_duration_seconds:
                        st.warning(f"Clip {idx+1}: Original end time ({end_time_str} / {end_seconds:.2f}s) exceeds source duration ({source_video_duration_seconds:.2f}s). Adjusting to source end.")
                        end_seconds = source_video_duration_seconds
                    
                    duration_seconds = end_seconds - start_seconds
                    if duration_seconds <= 0: # Should be caught by start_seconds >= end_seconds, but double check
                        st.error(f"Clip {idx+1}: Calculated duration is zero or negative ({duration_seconds:.2f}s) after adjustments.")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Invalid duration.")
                        continue

                    # 3. Construct output filename based on the original source filename
                    original_source_basename = os.path.splitext(source_gcs_filename)[0]
                    clip_output_filename = f"{original_source_basename}_{idx+1}.mp4"
                                        
                    final_clip_output_path = os.path.join(temp_ai_clips_individual_output_dir_param, clip_output_filename)
    
                    clip_status_message.info(f"Clip {idx+1}: Extracting '{source_gcs_filename}' (from {start_time_str} to {end_time_str}). Output: {clip_output_filename} to '{temp_ai_clips_individual_output_dir_param}'")

                    # Ensure the downloaded file exists before attempting FFmpeg processing
                    if not os.path.exists(local_downloaded_source_path) or os.path.getsize(local_downloaded_source_path) == 0:
                        st.error(f"Clip {idx+1}: Downloaded source file '{local_downloaded_source_path}' is missing or empty before FFmpeg.")
                        clips_with_errors += 1
                        clip_status_message.error(f"Clip {idx+1} Error: Source file issue before FFmpeg.")
                        continue

                    # 4. FFmpeg processing
                    ffmpeg_process = (
                        ffmpeg
                        .input(local_downloaded_source_path, ss=start_seconds, t=duration_seconds)
                        .output(final_clip_output_path, vcodec='libx264', acodec='aac', strict='experimental', preset='medium', crf=23, movflags='+faststart')
                        .overwrite_output()
                    )
                    ffmpeg_process.run(capture_stdout=True, capture_stderr=True)
                    
                    # If FFmpeg succeeds, then try to upload to GCS using gcs_output_clips_prefix_param
                    gcs_clip_destination_blob_name = f"{gcs_output_clips_prefix_param}{clip_output_filename}"
                    if not gcs_output_clips_prefix_param.endswith('/'): # ensure trailing slash
                        gcs_clip_destination_blob_name = f"{gcs_output_clips_prefix_param}/{clip_output_filename}"
                    try:
                        blob_uploader = gcs_bucket_downloader.blob(gcs_clip_destination_blob_name)
                        blob_uploader.upload_from_filename(final_clip_output_path)
                        generated_clip_paths_this_run.append(final_clip_output_path) # Store local path upon full success
                        clips_processed_successfully += 1
                        clip_status_message.success(f"Clip {idx+1}: '{clip_output_filename}' generated and uploaded to GCS (gs://{gcs_bucket_name_param}/{gcs_clip_destination_blob_name})")
                    except Exception as e_gcs_upload:
                        st.error(f"Clip {idx+1}: '{clip_output_filename}' generated locally, but GCS upload failed: {e_gcs_upload}")
                        generated_clip_paths_this_run.append(final_clip_output_path) # Still add local path for display
                        clips_with_errors += 1
                        # Note: clips_processed_successfully is NOT incremented here as GCS upload failed.
                        clip_status_message.warning(f"Clip {idx+1}: '{clip_output_filename}' generated locally, GCS upload FAILED.")


                except ffmpeg.Error as e_ffmpeg:
                    # Check if stderr is available and decode it
                    ffmpeg_error_details = "Unknown FFmpeg error"
                    if e_ffmpeg.stderr:
                        try:
                            ffmpeg_error_details = e_ffmpeg.stderr.decode('utf8')
                        except Exception:
                            ffmpeg_error_details = "FFmpeg error (stderr not decodable)"
                    st.error(f"Clip {idx+1} FFmpeg error for '{source_gcs_filename}': {ffmpeg_error_details}")
                    clips_with_errors += 1
                    clip_status_message.error(f"Clip {idx+1} Error: FFmpeg processing failed.")
                except ValueError as e_timecode: # From parse_timecode
                    st.error(f"Clip {idx+1} Timecode error for '{clip_data['timecode']}': {e_timecode}")
                    clips_with_errors += 1
                    clip_status_message.error(f"Clip {idx+1} Error: Invalid timecode value.")
                except Exception as e_clip_processing:
                    st.error(f"Clip {idx+1} General error processing '{source_gcs_filename}': {e_clip_processing}")
                    clips_with_errors += 1
                    clip_status_message.error(f"Clip {idx+1} Error: General processing failure.")
                finally:
                    # Clean up downloaded source file for this clip if it exists
                    if os.path.exists(local_downloaded_source_path):
                        try:
                            os.remove(local_downloaded_source_path)
                        except Exception as e_cleanup:
                            st.warning(f"Could not clean up temporary file {local_downloaded_source_path}: {e_cleanup}")
            # End of loop through clips
        # End of tempfile.TemporaryDirectory context (tmp_download_dir is cleaned up)

        st.session_state.generated_clips_paths_tab5 = generated_clip_paths_this_run
        if clips_processed_successfully > 0:
            st.success(f"Individual AI clip generation finished. {clips_processed_successfully} clips created in '{temp_ai_clips_individual_output_dir_param}'.")
            
            # --- Stitching Logic ---
            if clips_processed_successfully > 0: # Only proceed if individual clips were made
                st.info("Starting to stitch AI generated clips...")
                # generated_clip_paths_this_run contains full paths to successfully created individual clips in order
                
                if not generated_clip_paths_this_run: # Should be redundant due to outer check, but good for safety
                    st.error("No AI clips found to stitch (list is empty).")
                    return

                # Determine a base name for the stitched video from the first successfully processed clip's original source
                # This requires original_source_basename to be available from the loop.
                # We can get it from the first item in parsed_clip_data if that's reliable, or pass it.
                # For simplicity, let's try to get it from the first successfully processed clip's path.
                # This assumes generated_clip_paths_this_run is not empty.
                first_clip_path = generated_clip_paths_this_run[0]
                # Extract a base name, e.g., "cinta-buat-dara-S1E1_part1" from "cinta-buat-dara-S1E1_part1_1.mp4"
                # This might need adjustment based on actual naming from `output_basename_style`
                # A safer way: use the `output_basename_style` and remove the `_X.mp4` part if it exists.
                # For now, let's use a generic name or derive from the first source GCS filename if available.
                # `original_source_basename` is defined inside the loop, so it's not directly accessible here.
                # We need to ensure `original_source_basename` is correctly set for the stitched video name.
                # Let's use a fixed name for now or derive it more robustly if needed.
                # If parsed_clip_data is available and not empty:
                final_stitched_video_base_name = "ai_stitched_video"
                if parsed_clip_data:
                    first_source_gcs_file = parsed_clip_data[0]['source']
                    final_stitched_video_base_name = os.path.splitext(first_source_gcs_file)[0] + "_ai_stitched"


                final_stitched_video_filename = f"{final_stitched_video_base_name}.mp4"
                final_stitched_video_path = os.path.join(temp_ai_video_joined_output_dir_param, final_stitched_video_filename)

                # Create a temporary file list for ffmpeg concat
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmp_list_file:
                    for clip_path_stitch in generated_clip_paths_this_run: # Use the ordered list
                        tmp_list_file.write(f"file '{os.path.abspath(clip_path_stitch)}'\n")
                    temp_list_file_path = tmp_list_file.name
                
                try:
                    ffmpeg_concat_process = (
                        ffmpeg
                        .input(temp_list_file_path, format='concat', safe=0)
                        .output(final_stitched_video_path, c='copy') # Try to copy codecs first
                        .overwrite_output()
                    )
                    ffmpeg_concat_process.run(capture_stdout=True, capture_stderr=True)
                    st.success(f"Successfully stitched AI clips into '{final_stitched_video_path}'")
                    
                    with open(final_stitched_video_path, "rb") as fp_dl:
                        st.download_button(
                            label=f"Download Stitched AI Video: {final_stitched_video_filename}",
                            data=fp_dl,
                            file_name=final_stitched_video_filename,
                            mime="video/mp4",
                            key="download_stitched_ai_video_tab5"
                        )

                except ffmpeg.Error as e_concat:
                    st.error(f"Error during FFmpeg concatenation (codec copy attempt): {e_concat.stderr.decode('utf8') if e_concat.stderr else 'Unknown FFmpeg error'}")
                    st.info("Attempting concatenation with re-encoding as fallback...")
                    try:
                        ffmpeg_reencode_process = (
                            ffmpeg
                            .input(temp_list_file_path, format='concat', safe=0)
                            .output(final_stitched_video_path, vcodec='libx264', acodec='aac', strict='experimental') # Re-encode
                            .overwrite_output()
                        )
                        ffmpeg_reencode_process.run(capture_stdout=True, capture_stderr=True)
                        st.success(f"Successfully stitched AI clips (with re-encoding) into '{final_stitched_video_path}'")
                        with open(final_stitched_video_path, "rb") as fp_dl_reencode:
                            st.download_button(
                                label=f"Download Stitched AI Video (Re-encoded): {final_stitched_video_filename}",
                                data=fp_dl_reencode,
                                file_name=final_stitched_video_filename,
                                mime="video/mp4",
                                key="download_stitched_ai_video_reencode_tab5"
                            )
                    except ffmpeg.Error as e_reencode:
                        st.error(f"Error during FFmpeg concatenation (re-encode attempt): {e_reencode.stderr.decode('utf8') if e_reencode.stderr else 'Unknown FFmpeg error'}")
                finally:
                    os.remove(temp_list_file_path) # Clean up the temp file list
                    # Clean up individual AI clips after stitching
                    st.write("DEBUG: About to clean up individual AI clips.") # DEBUG
                    print(f"DEBUG: Paths to be cleaned: {generated_clip_paths_this_run}") # DEBUG
                    for clip_to_remove in generated_clip_paths_this_run:
                        print(f"DEBUG: Attempting to clean up: {clip_to_remove}") # DEBUG
                        if os.path.exists(clip_to_remove):
                            print(f"DEBUG: File exists, proceeding with deletion: {clip_to_remove}") # DEBUG
                            try:
                                os.remove(clip_to_remove)
                                print(f"DEBUG: Successfully removed: {clip_to_remove}") # DEBUG
                            except Exception as e_clean_clip:
                                st.warning(f"Could not remove temporary AI clip {clip_to_remove}: {e_clean_clip}")
                                print(f"DEBUG: Failed to remove {clip_to_remove}: {e_clean_clip}") # DEBUG
                        else:
                            print(f"DEBUG: File NOT found, skipping deletion: {clip_to_remove}") # DEBUG
                    if generated_clip_paths_this_run: # Only print if there were clips
                        st.info(f"Cleaned up individual AI clips from '{temp_ai_clips_individual_output_dir_param}'.")
                        print(f"DEBUG: Finished cleaning up individual AI clips from '{temp_ai_clips_individual_output_dir_param}'.") # DEBUG
                    else:
                        print("DEBUG: No individual AI clips were in generated_clip_paths_this_run to clean up.") # DEBUG
            # --- End of Stitching Logic ---

        if clips_with_errors > 0:
            st.error(f"{clips_with_errors} clips had errors during generation.")
        if clips_processed_successfully == 0 and clips_with_errors == 0 and parsed_clip_data: # This condition might need adjustment if we only generate AI list first
             st.warning("No clips were generated by FFMPEG, though no explicit errors were reported for clip processing steps.")
        # Removed the original `elif not parsed_clip_data:` as `parsed_clip_data` is now derived from AI output.
        # The check for empty `clip_details_text_for_processing` handles the case where AI output is empty.