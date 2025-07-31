import streamlit as st
import os
import re # Import re for regular expressions
from google.cloud import storage # Added for GCS listing
from typing import Optional
import ffmpeg # For clip generation
import tempfile # For temporary directory for GCS downloads

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

def render_tab3(
    gcs_bucket_name_param: str,
    # allowed_metadata_extensions: list = None # Future: if we want to filter by .txt, .json etc.
):
    st.header("Step 3: Clips Generation")

    # Define the output directory for generated clips, ensuring it's exactly as requested
    clips_output_dir = "./temp_clip_output"
    os.makedirs(clips_output_dir, exist_ok=True)

    # Session state for generated clip paths
    if "generated_clips_paths_tab3" not in st.session_state:
        st.session_state.generated_clips_paths_tab3 = []
    # Note: output_clip_filename_style_tab3 is initialized in app.py, so it should be available.

    # --- GCS Metadata File Listing and Selection ---
    st.subheader(f"Select Metadata File from gs://{gcs_bucket_name_param}/metadata/")
    gcs_metadata_files_options = [] # Renamed to avoid conflict with a potential global var
    error_listing_metadata = None
    metadata_gcs_prefix = "metadata/"
    
    # Function to load selected metadata content
    def load_selected_metadata_content_tab3(): # Renamed for clarity
        selected_file = st.session_state.get("selectbox_gcs_metadata_file_tab3")
        st.session_state.selected_gcs_metadata_file_tab3 = selected_file
        st.session_state.selected_gcs_metadata_content_tab3 = "" # Clear previous content
        if selected_file and selected_file != "-- Select a metadata file --":
            try:
                storage_client_load = storage.Client() # Use a distinct client instance
                bucket_load = storage_client_load.bucket(gcs_bucket_name_param)
                blob_load = bucket_load.blob(selected_file)
                if blob_load.exists():
                    content = blob_load.download_as_text()
                    st.session_state.selected_gcs_metadata_content_tab3 = content
                else:
                    st.session_state.selected_gcs_metadata_content_tab3 = f"Error: File '{selected_file}' not found in GCS."
            except Exception as e_load_meta:
                st.session_state.selected_gcs_metadata_content_tab3 = f"Error loading metadata file '{selected_file}': {e_load_meta}"
        elif selected_file == "-- Select a metadata file --":
             st.session_state.selected_gcs_metadata_file_tab3 = None # Ensure it's None if placeholder selected


    if not gcs_bucket_name_param:
        error_listing_metadata = "GCS Bucket name not provided. Please configure it in app settings."
        st.error(error_listing_metadata)
    else:
        try:
            storage_client_list = storage.Client()
            bucket_list = storage_client_list.bucket(gcs_bucket_name_param)
            
            # Fetch actual files and sort them
            actual_files = [b.name for b in bucket_list.list_blobs(prefix=metadata_gcs_prefix) if not b.name.endswith('/')]
            actual_files.sort()
            gcs_metadata_files_options = ["-- Select a metadata file --"] + actual_files


            if len(gcs_metadata_files_options) <= 1 : # Only placeholder exists
                st.warning(f"No metadata files found in 'gs://{gcs_bucket_name_param}/{metadata_gcs_prefix}'.")
            else:
                st.success(f"Found {len(gcs_metadata_files_options) - 1} metadata file(s) in 'gs://{gcs_bucket_name_param}/{metadata_gcs_prefix}'.")
                
                current_selection_index = 0
                # Check if a previous selection exists and is valid
                if st.session_state.selected_gcs_metadata_file_tab3 and st.session_state.selected_gcs_metadata_file_tab3 in gcs_metadata_files_options:
                    current_selection_index = gcs_metadata_files_options.index(st.session_state.selected_gcs_metadata_file_tab3)
                
                # If current selection is placeholder but there are actual files, default to first actual file
                elif current_selection_index == 0 and len(gcs_metadata_files_options) > 1:
                     pass # Keep placeholder selected by default initially

                st.selectbox(
                    "Choose a metadata file to view:",
                    options=gcs_metadata_files_options,
                    index=current_selection_index,
                    key="selectbox_gcs_metadata_file_tab3",
                    on_change=load_selected_metadata_content_tab3 # Use renamed function
                )
                
                # This logic attempts to auto-load if a selection exists from a previous run.
                # The on_change should handle most cases, but this can catch initial states.
                if st.session_state.selected_gcs_metadata_file_tab3 and \
                   st.session_state.selected_gcs_metadata_file_tab3 != "-- Select a metadata file --" and \
                   not st.session_state.selected_gcs_metadata_content_tab3:
                    # If a file is selected in session_state, but content is empty, try to load it.
                    # This is particularly for the case where the page reloads with a selection already made.
                    load_selected_metadata_content_tab3()


        except Exception as e_list_meta:
            error_listing_metadata = f"Error listing metadata files from GCS (gs://{gcs_bucket_name_param}/{metadata_gcs_prefix}): {e_list_meta}"
            st.error(error_listing_metadata)

    # Display selected metadata content
    if st.session_state.selected_gcs_metadata_file_tab3 and st.session_state.selected_gcs_metadata_content_tab3:
        st.subheader(f"Content of: `{st.session_state.selected_gcs_metadata_file_tab3}`")
        is_json_like = st.session_state.selected_gcs_metadata_content_tab3.strip().startswith('{') or \
                       st.session_state.selected_gcs_metadata_content_tab3.strip().startswith('[')
        if is_json_like:
            try:
                import json
                json_content = json.loads(st.session_state.selected_gcs_metadata_content_tab3)
                st.json(json_content)
            except json.JSONDecodeError:
                st.text_area("Metadata Content (non-JSON):", value=st.session_state.selected_gcs_metadata_content_tab3, height=300, disabled=True, key="metadata_content_display_tab3_txt_fallback")
        else:
            st.text_area("Metadata Content:", value=st.session_state.selected_gcs_metadata_content_tab3, height=300, disabled=True, key="metadata_content_display_tab3_text")
    elif st.session_state.selected_gcs_metadata_file_tab3 and \
         st.session_state.selected_gcs_metadata_file_tab3 != "-- Select a metadata file --" and \
         not st.session_state.selected_gcs_metadata_content_tab3.startswith("Error:"):
        pass
    elif st.session_state.selected_gcs_metadata_content_tab3.startswith("Error:"):
        st.error(st.session_state.selected_gcs_metadata_content_tab3)

    # --- Helper function to parse a single metadata content string ---
    def _parse_single_metadata_content(metadata_content_str: str) -> Optional[list]:
        """
        Parses a single metadata content string (expected to be JSON).
        Cleans common issues like ```json fences and extracts clip details.
        Returns a list of strings (each "filename\ntimestamp") or None on critical error.
        """
        if not metadata_content_str:
            # st.warning("Parser received empty metadata content.") # Keep this silent for batch processing
            return []

        try:
            import json # Keep import here for now, or ensure it's at top-level
            print(f"DEBUG: _parse_single_metadata_content received:\n---\n{metadata_content_str}\n---")

            temp_content_for_prefix_strip = metadata_content_str
            # Remove ```json prefix and anything before the first actual JSON character ([ or {)
            temp_content_for_prefix_strip = re.sub(r"^\s*(?:```json)?\s*.*?([\{\[])", r"\1", temp_content_for_prefix_strip, count=1, flags=re.DOTALL)

            temp_content_for_suffix_strip = temp_content_for_prefix_strip.strip()
            if temp_content_for_suffix_strip.endswith("```"):
                temp_content_for_suffix_strip = temp_content_for_suffix_strip[:-len("```")].strip()
            
            content_to_parse = temp_content_for_suffix_strip

            print(f"DEBUG: Content for json.loads() in _parse_single_metadata_content:\n---\n{content_to_parse}\n---")

            if not (content_to_parse.startswith('[') and content_to_parse.endswith(']')) and \
               not (content_to_parse.startswith('{') and content_to_parse.endswith('}')):
                print("DEBUG: Regex/strip cleaning failed or produced non-JSON, attempting aggressive find.")
                start_brace = content_to_parse.find('[')
                start_curly = content_to_parse.find('{')
                if start_brace == -1 and start_curly == -1:
                    st.error(f"Could not find starting '[' or '{{' in metadata snippet: '{content_to_parse[:100]}...'")
                    return None
                start_index = min(start_brace, start_curly) if start_brace != -1 and start_curly != -1 else (start_brace if start_brace != -1 else start_curly)
                
                end_brace = content_to_parse.rfind(']')
                end_curly = content_to_parse.rfind('}')
                if end_brace == -1 and end_curly == -1:
                    st.error(f"Could not find ending ']' or '}}' in metadata snippet: '...{content_to_parse[-100:]}'")
                    return None
                end_index = max(end_brace, end_curly) if end_brace != -1 and end_curly != -1 else (end_brace if end_brace != -1 else end_curly)
                
                if start_index != -1 and end_index != -1 and start_index < end_index:
                    content_to_parse = content_to_parse[start_index : end_index+1]
                    print(f"DEBUG: Content after AGGRESSIVE FIND:\n---\n{content_to_parse}\n---")
                else:
                    st.error("JSON start/end markers found in incorrect order or not found by aggressive search.")
                    return None

            parsed_content = json.loads(content_to_parse)
            
            if not isinstance(parsed_content, list):
                st.error("Parsed metadata is not a valid JSON array of clips.")
                return None

            extracted_details = []
            for item in parsed_content:
                if isinstance(item, dict):
                    filename = item.get("source_filename")
                    timestamp = item.get("timestamp_start_end")
                    if filename and timestamp:
                        extracted_details.append(f"{filename}\n{timestamp}")
                    else:
                        st.warning(f"Skipping item due to missing 'source_filename' or 'timestamp_start_end': {item}")
                else:
                    st.warning(f"Skipping non-dictionary item in metadata: {item}")
            return extracted_details

        except json.JSONDecodeError as e:
            st.error(f"Failed to parse metadata content as JSON: {e}. Problematic content snippet: '{content_to_parse[:200]}...'")
            return None
        except Exception as e_extract:
            st.error(f"An error occurred during metadata parsing: {e_extract}")
            return None

    # --- Button to Extract Clip Details (for single selected file) ---
    def extract_and_populate_clip_details():
        try:
            print(f"DEBUG: extract_and_populate_clip_details called. Selected file: {st.session_state.get('selected_gcs_metadata_file_tab3')}")
            metadata_content = st.session_state.get("selected_gcs_metadata_content_tab3", "")
            
            if not metadata_content or metadata_content.startswith("Error:"):
                st.error("No valid metadata content selected or loaded to extract details from.")
                return

            extracted_details = _parse_single_metadata_content(metadata_content)

            if extracted_details is not None: # Successfully parsed (could be empty list)
                if extracted_details:
                    new_clip_details_content = "\n".join(extracted_details)
                    st.session_state.trailer_details_input_content_tab3 = new_clip_details_content
                    st.success(f"Successfully extracted {len(extracted_details)} clip details from selected file.")

                    # Attempt to set the default filename style
                    if new_clip_details_content:
                        first_line = new_clip_details_content.split('\n')[0].strip()
                        if first_line.endswith(".mp4"):
                            base_name_parts = first_line.split('_part')
                            if base_name_parts: # Check if split produced more than one part
                                base_name = base_name_parts[0]
                                st.session_state.output_clip_filename_style_tab3 = f"{base_name}_part1_x.mp4"
                            else: # If '_part' is not in the filename
                                base_name_no_ext = os.path.splitext(first_line)[0]
                                st.session_state.output_clip_filename_style_tab3 = f"{base_name_no_ext}_part1_x.mp4"
                        else: # If filename does not end with .mp4 (edge case)
                             base_name_no_ext = os.path.splitext(first_line)[0]
                             st.session_state.output_clip_filename_style_tab3 = f"{base_name_no_ext}_part1_x.mp4"

                else: # Parsed successfully, but no details found
                    st.warning("No clip details (source_filename, timestamp_start_end) found in the selected metadata.")
                    st.session_state.trailer_details_input_content_tab3 = "" # Clear if nothing found
            # If extracted_details is None, _parse_single_metadata_content already showed an error.
        except Exception as e_callback:
            st.error(f"An unexpected error occurred in 'Extract Clip Details' callback: {e_callback}")
            st.exception(e_callback) # This will print the full traceback

    # --- Function to Extract All Clip Details (from all GCS files) ---
    def extract_all_clips_details():
        print(f"DEBUG: extract_all_clips_details called.")
        # gcs_metadata_files_options is defined in the outer scope of render_tab3
        # We need to ensure it's accessible here or passed if it's not in the direct closure.
        # For now, assuming it's accessible via st.session_state or directly if defined before this call.
        # A safer way would be to retrieve it from where it's populated or pass it.
        # Let's assume `gcs_metadata_files_options` is available in the scope it's used.

        # Check if gcs_metadata_files_options has been populated
        if not gcs_metadata_files_options or len(gcs_metadata_files_options) <= 1:
            st.warning("No GCS metadata files found to process for 'Extract All Clips'.")
            return

        all_extracted_details_across_files = []
        files_processed_count = 0
        files_with_errors_count = 0
        
        # Get a fresh GCS client
        try:
            storage_client_extract_all = storage.Client()
            bucket_extract_all = storage_client_extract_all.bucket(gcs_bucket_name_param)
        except Exception as e_client:
            st.error(f"Failed to initialize GCS client for 'Extract All Clips': {e_client}")
            return

        for gcs_file_path in gcs_metadata_files_options:
            if gcs_file_path == "-- Select a metadata file --":
                continue # Skip the placeholder

            try:
                print(f"DEBUG: Processing file for 'Extract All': {gcs_file_path}")
                blob_extract = bucket_extract_all.blob(gcs_file_path)
                if blob_extract.exists():
                    content_str = blob_extract.download_as_text()
                    single_file_details = _parse_single_metadata_content(content_str)
                    if single_file_details is not None: # Parsing attempted (might be empty list)
                        all_extracted_details_across_files.extend(single_file_details)
                        files_processed_count +=1
                    else: # Parsing failed critically for this file
                        st.error(f"Failed to parse details from GCS file: {gcs_file_path}")
                        files_with_errors_count += 1
                else:
                    st.warning(f"GCS file not found during 'Extract All': {gcs_file_path}")
                    files_with_errors_count += 1
            except Exception as e_gcs_download:
                st.error(f"Error downloading or processing GCS file {gcs_file_path}: {e_gcs_download}")
                files_with_errors_count += 1
        
        if all_extracted_details_across_files:
            final_content_for_textarea = "\n".join(all_extracted_details_across_files)
            st.session_state.trailer_details_input_content_tab3 = final_content_for_textarea
            st.success(f"Successfully extracted {len(all_extracted_details_across_files)} clip details from {files_processed_count} GCS file(s). {files_with_errors_count} file(s) had errors.")

            # Attempt to set the default filename style from the new combined content
            if final_content_for_textarea:
                first_line = final_content_for_textarea.split('\n')[0].strip()
                if first_line.endswith(".mp4"):
                    base_name_parts = first_line.split('_part')
                    if base_name_parts:
                        base_name = base_name_parts[0]
                        st.session_state.output_clip_filename_style_tab3 = f"{base_name}_part1_x.mp4"
                    else:
                        base_name_no_ext = os.path.splitext(first_line)[0]
                        st.session_state.output_clip_filename_style_tab3 = f"{base_name_no_ext}_part1_x.mp4"
        else:
            st.warning(f"No clip details extracted from any GCS files. Processed {files_processed_count} file(s). {files_with_errors_count} file(s) had errors.")
            st.session_state.trailer_details_input_content_tab3 = "" # Clear if nothing found

    # --- UI for Buttons ---
    # The gcs_metadata_files_options is populated around line 50.
    # We should ensure buttons are only shown if there's something to process or select.
    
    # Condition for showing "Extract Clip Details" (single selected file)
    show_extract_single_button = (
        st.session_state.get("selected_gcs_metadata_file_tab3") and
        st.session_state.get("selected_gcs_metadata_file_tab3") != "-- Select a metadata file --" and
        st.session_state.get("selected_gcs_metadata_content_tab3") and
        not st.session_state.get("selected_gcs_metadata_content_tab3", "").startswith("Error:")
    )

    # Condition for showing "Extract All Clips" (any GCS files available, excluding placeholder)
    show_extract_all_button = gcs_metadata_files_options and len(gcs_metadata_files_options) > 1

    if show_extract_single_button or show_extract_all_button:
        col1, col2 = st.columns(2)
        with col1:
            if show_extract_single_button:
                if st.button("📋 Extract Clip Details", key="extract_selected_clip_details_button", help="Extracts details from the currently selected metadata file above."):
                    extract_and_populate_clip_details()
            else:
                st.empty() # Keep column structure if button is not shown
        
        with col2:
            if show_extract_all_button:
                if st.button("📚 Extract All Clips", key="extract_all_clips_button", help="Extracts details from ALL metadata files listed from GCS."):
                    extract_all_clips_details()
            else:
                st.empty() # Keep column structure if button is not shown
    
    st.markdown("---")
    # Input area for trailer details (e.g., from metadata files or manual input)
    st.write("""
    Provide details for clip generation. This might involve specifying metadata files,
    or manually listing video segments and their desired properties.
    (The exact format and processing logic will be defined later)
    """)
    
    # Controlled text_area
    st.text_area(
        "Clip Generation Details:",
        value=st.session_state.trailer_details_input_content_tab3,
        height=200,
        key="trailer_details_textarea_widget", # Use a distinct key for the widget
        on_change=lambda: setattr(st.session_state, 'trailer_details_input_content_tab3', st.session_state.trailer_details_textarea_widget)
    )

    # Use a key for the widget itself to ensure its state is managed by Streamlit
    st.text_input(
        "Clip filename style:",
        value=st.session_state.output_clip_filename_style_tab3,
        key="text_input_clip_filename_style_tab3", # Widget key
        on_change=lambda: setattr(st.session_state, 'output_clip_filename_style_tab3', st.session_state.text_input_clip_filename_style_tab3)
    )
    
    # os.makedirs(clips_output_dir, exist_ok=True) # Moved to the top of render_tab3

    generate_clips_button_disabled = not bool(st.session_state.get("trailer_details_input_content_tab3", "").strip())

    if st.button("✨ Generate Clips", key="generate_clips_button_tab3", disabled=generate_clips_button_disabled):
        st.session_state.generated_clips_paths_tab3 = [] # Clear previous clips
        
        clip_details_text = st.session_state.trailer_details_input_content_tab3.strip()
        output_basename_style = st.session_state.output_clip_filename_style_tab3.strip()

        if not output_basename_style:
            st.error("Please enter a valid clip filename style/basename.")
            return

        clip_entries = clip_details_text.split('\n')
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

        with tempfile.TemporaryDirectory(prefix="gcs_downloads_tab3_") as tmp_download_dir:
            for idx, clip_data in enumerate(parsed_clip_data):
                source_gcs_filename = clip_data['source']
                # Assuming source videos are in a 'processed/' prefix, adjust if different
                # This prefix should ideally come from app.py's PROCESSED_GCS_FOLDER_NAME
                # For now, hardcoding 'processed/' as per previous assumption.
                source_gcs_blob_path = f"processed/{source_gcs_filename}"
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
                                        
                    final_clip_output_path = os.path.join(clips_output_dir, clip_output_filename)
    
                    clip_status_message.info(f"Clip {idx+1}: Extracting '{source_gcs_filename}' (from {start_time_str} to {end_time_str}). Output: {clip_output_filename}")

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
                    
                    # If FFmpeg succeeds, then try to upload to GCS
                    gcs_clip_destination_blob_name = f"clips/{clip_output_filename}"
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

        st.session_state.generated_clips_paths_tab3 = generated_clip_paths_this_run
        if clips_processed_successfully > 0:
            st.success(f"Clip generation finished. {clips_processed_successfully} clips generated successfully in '{clips_output_dir}'.")
        if clips_with_errors > 0:
            st.error(f"{clips_with_errors} clips had errors during generation.")
        if clips_processed_successfully == 0 and clips_with_errors == 0 and parsed_clip_data:
             st.warning("No clips were generated, though no explicit errors were reported for clip processing steps.")
        elif not parsed_clip_data: # This case should have been caught earlier
            st.error("No valid clip entries were found to process.")

