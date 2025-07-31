import streamlit as st
import os
import threading
import asyncio
import time # Added for sleep
from google.cloud import storage
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx
import google.generativeai as genai
import subprocess # Added for ffprobe
import tempfile # Added for potential temporary downloads
import nest_asyncio
import logging

# Apply nest_asyncio once at the start of the script if needed globally
# Or, ensure it's applied before any new event loop is started by asyncio.run() in a thread.
# For simplicity here, it's in batch_process_metadata_threaded, but consider moving if it causes issues.

# --- Your prompt_text variable (this is now the DEFAULT TEMPLATE) ---
# It's good to define it here so render_tab2 can use it as a default
# for st.session_state.batch_prompt_text_area_content
default_prompt_template = """
You are a professional film and drama editor AI, equipped with multimodal understanding (visuals, dialogue, sound, and inferred emotion). Your task is to meticulously analyze the provided video content of an **appmaximum 10-minute video clip from a drama series.** Your goal is to identify multiple key moments suitable for constructing a dynamic and engaging 2-minute trailer from **this specific clip.**

For each potential trailer moment you identify **within this video clip**, extract and structure the following metadata. Be precise and insightful.

**Input to Analyze:**
*   **Primary:** The video content of the drama clip named **`{{source_filename}}`**. This clip is **`{{actual_video_duration}}`** long. Make sure you only capture scenes within the actual length of *this specific video clip*.
*   **Supplementary (if provided):** A transcript or scene-by-scene description. Your analysis should prioritize what is seen and heard in the video, using supplementary text to clarify or confirm dialogue and scene context if available.

**Prioritize Moments That (within the ~10-minute clip):**
*   Introduce key characters effectively.
*   Establish the central conflict or mystery.
(Rest of the prioritization list)

**Output Requirements:**
Provide your response as a single, valid JSON array. Each element in the array should be a JSON object representing one potential trailer clip. Each object must contain the following fields:

1.  **`source_filename`**:
    *   Description: The filename of the video clip being analyzed (which is **`{{source_filename}}`**).
    *   Example: "cinta-buat-dara-S1E1_part1.mp4"
2.  **`timestamp_start_end`**:
    *   Description: Precise in and out points for the clip (HH:MM:SS - HH:MM:SS) **relative to the start of the provided video file.** Aim for clips 2-15 seconds long. **All timestamps (both start and end) MUST be within the actual duration of the input video clip `source_filename`. Do not generate timestamps exceeding the video's length.**
    *   Example: "00:02:15 - 00:02:30" (This would be valid for a 10-minute clip, but "00:12:00 - 00:12:10" would be invalid).
3.  **`editor_note_clip_rationale`**:
    *   Description: Your rationale for selecting this clip. Why is it trailer-worthy? (Max 30 words)
    *   Example: "The mother threatens Dara's prized possession, creating a cliffhanger for her rebellious streak and showcasing immediate conflict."
4.  **’brief_scene_description‘**:
    *   Description: Concisely summarize the core action, setting, and characters. Focus on visual/narrative significance. (Max 25 words)
    *   Example: "Character A confronts Character B in a dimly lit alley during a storm. Close up on A's determined, angry face."
5.  **‘key_dialogue_snippet’**:
    *   Description: Most potent intriguing, or revealing line(s) of dialogue (verbatim, max 2 lines). If none, state "None" or "Action/Visual Only."
    *   Example: "Mama: "Mama tahu macam mana nak ubat Dara!" Dara: (Screaming) "No! Mama! Mama, Dara minta maaf Mama!""
6.  **’dominant_emotional_tone_impact‘:
    *   Description: Primary feeling(s) or impact evoked. (Max 5 keywords, comma-separated)
    *   Example: "Tense, Confrontational, Betrayal, Shock, Anger"
7.  **‘key_visual_elements_cinematography’:
    *   Description: Striking visuals, camera work, lighting, significant props/symbols. (Max 5 keywords/phrases, comma-separated)
    *   Example: "Dramatic low-angle, Rain-streaked, Fast cuts, Close-up on eyes, Flickering neon sign"
8.  **·characters_in_focus_objective_emotion‘:
    *   Description: Who is central? Their objective or strong emotion? (Max 15 words)
    *   Example: "Sarah (desperate) trying to escape."
9.  **plot_relevance_significance’:
    *   Description: Why is this moment important for the narrative or trailer? (Max 20 words)
    *   Example: "Introduces main antagonist and the core personal conflict."
10. **trailer_potential_category‘:
    *   Description: How could this clip be used? (Choose one or two from list, comma-separated)
    *   Options: Hook/Opening, Character Introduction, Inciting Incident, Conflict Build-up, Rising Action, Tension/Suspense Peak, Emotional Beat, Action Sequence Highlight, Twist/Reveal Tease, Climax Tease, Resolution Glimpse, Cliffhanger/Question, Thematic Montage Element
    *   Example: "Cliffhanger/Question, Tension/Suspense Peak"
11. **pacing_suggestion_for_clip’:
    *   Description: How should this clip feel in a trailer sequence? (Choose one from list)
    *   Options: Rapid Cut, Medium Pace, Slow Burn/Held Shot, Builds Intensity, Sudden Impact
    *   Example: "Builds Intensity"
12. **music_sound_cue_idea‘:
    *   Description: Optional. Sound to amplify the moment. (Max 10 words)
    *   Example: "Sudden silence then impact sound."

    *Crucial JSON Formatting Rules:
    *The generated JSON must be strictly valid according to standard JSON syntax (RFC 8259).
    *Specifically, ensure there are NO TRAILING COMMAS after the last element in an array or the last key-value pair in an object. For example, ["item1", "item2"] is correct, but ["item1", "item2",] is incorrect. Similarly, {{"key1": "value1", "key2": "value2"}} is correct, but {{"key1": "value1", "key2": "value2",}} is incorrect.
    *All strings within the JSON (keys and values) must be enclosed in double quotes and properly escaped if they contain special characters (e.g., double quotes within a string should be escaped as \").
    *If a category (diagnoses, observations, etc.) has no items, use an empty array [] for that category's list. For the summary, if no summary can be generated, provide an empty string "" or a "None available." string.
    *After generating the JSON, please perform a quick check to ensure it is valid JSON syntax according to the rules mentioned above.
    *A common error is forgetting a comma or a colon between elements. For instance,
    *{{"description\": \"A\" \"codes\": [\"C\"] is WRONG because it's missing a comma after \"A\". It should be {{\"description\": \"A\", \"codes\": [\"C\"]}}.
    *Please meticulously check for missing commas before outputting the JSON.
    *Is there an unclosed string (") on a previous line that's making the parser confused?
    *Is all property enclosed with double quote (")
"""

# --- Helper function to get video duration ---
def get_video_duration_ffmpeg(video_path: str) -> str:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
        )
        duration_seconds = float(result.stdout.strip())
        if duration_seconds < 0: duration_seconds = 0
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        seconds = int(duration_seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except FileNotFoundError:
        st.error("`ffprobe` command not found. Ensure FFmpeg is installed and in PATH.")
        # Log this error as well, as st.error might not be visible from a thread without context
        print("ERROR: `ffprobe` command not found.")
        raise # Re-raise to be caught by the caller if needed
    except subprocess.CalledProcessError as e:
        print(f"Error getting duration for {video_path} with ffprobe. stderr: {e.stderr}")
        return "00:00:00"
    except ValueError as e:
        print(f"Error parsing ffprobe duration output for {video_path}: {e}. Output: '{result.stdout.strip() if 'result' in locals() else 'N/A'}'")
        return "00:00:00"
    except Exception as e:
        print(f"Unexpected error getting duration for {video_path}: {e}")
        return "00:00:00"

# Configure logger for tenacity
logger = logging.getLogger(__name__)
# Ensure logging is configured to show warnings for tenacity retries
if not logger.handlers: # Avoid adding multiple handlers if re-running script parts
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING) # Use tenacity's built-in logger
)
async def call_gemini_api_async(gcs_video_uri: str, prompt_text_for_api: str, gemini_api_key: str, video_filename_key: str, ai_model_name: str): # Added ai_model_name
    # ... (call_gemini_api_async content is mostly fine, ensure it uses prompt_text_for_api)
    st.session_state.batch_processed_files[video_filename_key] = f"Processing: {video_filename_key}"
    st.session_state.live_streaming_outputs[video_filename_key] = "Processing..."
    try:
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY not provided.")
        # genai.configure should be handled by app.py or get_model.py globally
        # If re-configuration per call is needed, it can be done, but usually not necessary if key doesn't change
        # genai.configure(api_key=gemini_api_key)
        model_instance = genai.GenerativeModel(model_name=ai_model_name) # Use passed model name
        st.session_state.live_streaming_outputs[video_filename_key] = f"Preparing video from GCS: {video_filename_key}..."
        contents_for_api = [gcs_video_uri, prompt_text_for_api] # Use the passed, formatted prompt
        generation_config = genai.types.GenerationConfig(temperature=1.0, top_p=1.0, max_output_tokens=8192)
        safety_settings = [
            {"category": genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
        ]
        tools = None
        st.session_state.live_streaming_outputs[video_filename_key] = f"Starting analysis for {video_filename_key}..."
        print(f"[DEBUG call_gemini_api_async] Calling generate_content_async for {video_filename_key} with model {model_instance.model_name}")
        # For debugging the exact prompt sent:
        # print(f"--- PROMPT FOR {video_filename_key} ---\n{prompt_text_for_api}\n----------------------------")

        response = await model_instance.generate_content_async(
            contents=contents_for_api, generation_config=generation_config, safety_settings=safety_settings, tools=tools
        )
        full_response_text = ""
        if hasattr(response, 'text') and response.text:
            full_response_text = response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part_item in response.candidates[0].content.parts:
                 if hasattr(part_item, 'text'): full_response_text += part_item.text
        elif response.parts:
            for part_item in response.parts:
                if hasattr(part_item, 'text'): full_response_text += part_item.text

        if not full_response_text and response.prompt_feedback:
            block_reason = getattr(response.prompt_feedback, 'block_reason', None)
            if block_reason:
                reason_message = block_reason.name
                if hasattr(response.prompt_feedback, 'block_reason_message') and response.prompt_feedback.block_reason_message:
                    reason_message = f"{reason_message} ({response.prompt_feedback.block_reason_message})"
                error_msg = f"Content generation blocked for '{video_filename_key}'. Reason: {reason_message}"
                st.session_state.batch_processed_files[video_filename_key] = f"Error: {error_msg}"
                st.session_state.live_streaming_outputs[video_filename_key] = f"--- ERROR ---\n{error_msg}"
                print(f"[DEBUG call_gemini_api_async] Content blocked: {video_filename_key}, Reason: {reason_message}")
                return
        st.session_state.batch_processed_files[video_filename_key] = f"Processed: {video_filename_key} ({len(full_response_text)} chars) (Pending Save)"
        st.session_state.live_streaming_outputs[video_filename_key] = full_response_text
        print(f"[DEBUG call_gemini_api_async] Successfully processed: {video_filename_key}, Response length: {len(full_response_text)}")
    except Exception as e:
        error_msg = f"Gemini API error for '{video_filename_key}': {type(e).__name__} - {e}"
        st.session_state.batch_processed_files[video_filename_key] = f"Error: {error_msg}"
        st.session_state.live_streaming_outputs[video_filename_key] = f"--- API ERROR ---\n{error_msg}"
        raise


def batch_process_metadata_threaded(
    parent_ctx, selected_gcs_video_uris, 
    # This is the template from the UI's text_area
    ui_edited_prompt_template_text: str,
    metadata_output_dir, gemini_api_key_for_batch,
    ai_model_name_for_batch: str, # Added
    concurrent_api_calls_limit, gcs_bucket_name_for_upload,
    gcs_output_metadata_prefix_for_batch: str # Added
):
    if parent_ctx:
        add_script_run_ctx(threading.current_thread(), parent_ctx)
    
    nest_asyncio.apply()

    st.session_state.is_batch_processing = True
    # Initialize file statuses in session_state (done in render_tab2 before thread start, but good to confirm)
    # for gcs_uri in selected_gcs_video_uris:
    #     fn_key = os.path.basename(gcs_uri)
    #     if fn_key not in st.session_state.batch_processed_files: # Avoid overwriting if already processing
    #         st.session_state.batch_processed_files[fn_key] = f"Queued: {fn_key}"
    #         st.session_state.live_streaming_outputs[fn_key] = "Queued..."
    # st.session_state.batch_processing_errors = [] # Should be reset in render_tab2
    # st.session_state.batch_progress_value = 0
    # st.session_state.batch_progress_text = "Initializing batch processing..."
    # No st.rerun() needed here immediately

    total_files = len(selected_gcs_video_uris)
    os.makedirs(metadata_output_dir, exist_ok=True)
    files_processed_successfully_count = 0
    files_with_errors_count = 0 # Counts files with API errors or local save errors

    def download_gcs_file_temporarily(bucket_name, blob_name):
        try:
            storage_client_download = storage.Client() # Create client inside thread
            bucket = storage_client_download.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(blob_name)[1]) as temp_file:
                print(f"[INFO] Downloading gs://{bucket_name}/{blob_name} to {temp_file.name} for duration check.")
                blob.download_to_filename(temp_file.name)
                return temp_file.name
        except Exception as e_download:
            print(f"Error downloading GCS file gs://{bucket_name}/{blob_name} for duration check: {e_download}")
            st.session_state.batch_processing_errors.append(f"Download failed for {blob_name}: {e_download}")
            return None

    async def _process_batch_async():
        nonlocal files_processed_successfully_count, files_with_errors_count
        semaphore = asyncio.Semaphore(concurrent_api_calls_limit)
        tasks = []

        for i, gcs_video_uri_item in enumerate(selected_gcs_video_uris):
            video_filename_key = os.path.basename(gcs_video_uri_item)
            gcs_bucket_name = gcs_video_uri_item.split('/')[2]
            gcs_blob_name = '/'.join(gcs_video_uri_item.split('/')[3:])
            
            # Download outside the process_one_video to avoid doing it inside the semaphore if possible,
            # though it's still per-video.
            temp_local_video_path = download_gcs_file_temporarily(gcs_bucket_name, gcs_blob_name)

            async def process_one_video(current_gcs_uri, fn_key_for_status, current_index, local_path_for_duration):
                nonlocal files_with_errors_count, files_processed_successfully_count
                
                # Use the ui_edited_prompt_template_text passed to the parent threaded function
                prompt_for_this_segment = ui_edited_prompt_template_text 

                if local_path_for_duration:
                    try:
                        st.session_state.live_streaming_outputs[fn_key_for_status] = f"Getting duration for {fn_key_for_status}..."
                        actual_duration_str = get_video_duration_ffmpeg(local_path_for_duration)
                        st.session_state.live_streaming_outputs[fn_key_for_status] = f"Duration for {fn_key_for_status}: {actual_duration_str}. Preparing prompt..."
                        print(f"[INFO] Duration for {fn_key_for_status}: {actual_duration_str}")
                        
                        prompt_for_this_segment = prompt_for_this_segment.replace("{{actual_video_duration}}", actual_duration_str)
                        prompt_for_this_segment = prompt_for_this_segment.replace("{{source_filename}}", fn_key_for_status)

                    except Exception as e_duration: # Catch errors from get_video_duration_ffmpeg specifically
                        print(f"Error getting duration or customizing prompt for {fn_key_for_status}: {e_duration}")
                        st.session_state.live_streaming_outputs[fn_key_for_status] = f"Error getting duration for {fn_key_for_status}: {e_duration}. Using modified default prompt."
                        st.session_state.batch_processing_errors.append(f"Duration check failed for {fn_key_for_status}: {e_duration}")
                        
                        prompt_for_this_segment = ui_edited_prompt_template_text.replace("{{source_filename}}", fn_key_for_status)
                        prompt_for_this_segment = prompt_for_this_segment.replace(f" This clip is **`{{{{actual_video_duration}}}}`** long.", " The precise duration of this clip is undetermined, but it is a short segment.")
                        prompt_for_this_segment = prompt_for_this_segment.replace("{{actual_video_duration}}", "its actual end time") # More generic fallback
                    finally:
                        if local_path_for_duration and local_path_for_duration.startswith(tempfile.gettempdir()):
                            try:
                                os.remove(local_path_for_duration)
                                print(f"[INFO] Removed temporary file: {local_path_for_duration}")
                            except OSError as e_remove:
                                print(f"Error removing temporary file {local_path_for_duration}: {e_remove}")
                else: # temp_local_video_path was None (download failed)
                    st.warning(f"Could not download {fn_key_for_status} to determine duration. Using modified default prompt.")
                    st.session_state.live_streaming_outputs[fn_key_for_status] = f"Download failed for {fn_key_for_status}. Using modified default prompt."
                    prompt_for_this_segment = ui_edited_prompt_template_text.replace("{{source_filename}}", fn_key_for_status)
                    prompt_for_this_segment = prompt_for_this_segment.replace(f" This clip is **`{{{{actual_video_duration}}}}`** long.", " The precise duration of this clip is undetermined due to a download issue, but it is a short segment.")
                    prompt_for_this_segment = prompt_for_this_segment.replace("{{actual_video_duration}}", "its actual end time")

                try:
                    async with semaphore:
                        print(f"[DEBUG process_one_video] Starting API call for: {fn_key_for_status} (Index: {current_index})")
                        st.session_state.batch_progress_text = f"API call for file {current_index + 1}/{total_files}: {fn_key_for_status}"
                        # Update live output for current file being processed by API
                        st.session_state.live_streaming_outputs[fn_key_for_status] = f"Calling Gemini API for {fn_key_for_status}..."


                        await call_gemini_api_async(
                            current_gcs_uri,
                            prompt_for_this_segment,
                            gemini_api_key_for_batch,
                            fn_key_for_status,
                            ai_model_name_for_batch # Pass model name
                        )
                        if "Error:" not in st.session_state.batch_processed_files.get(fn_key_for_status, ""):
                            full_response_text = st.session_state.live_streaming_outputs.get(fn_key_for_status, "")
                            st.session_state.batch_processed_files[fn_key_for_status] = f"Saving: {fn_key_for_status} ({len(full_response_text)} chars)"
                            base_name, _ = os.path.splitext(fn_key_for_status)
                            output_txt_filename = f"{base_name}.txt"
                            local_output_path = os.path.join(metadata_output_dir, output_txt_filename)
                            try:
                                with open(local_output_path, "w", encoding="utf-8") as f: f.write(full_response_text)
                                st.session_state.batch_processed_files[fn_key_for_status] = "Success (Saved Locally)"
                                st.session_state.live_streaming_outputs[fn_key_for_status] = f"Successfully saved locally.\n\n{full_response_text}"
                                try:
                                    st.session_state.batch_processed_files[fn_key_for_status] = f"Uploading to GCS: {fn_key_for_status}"
                                    st.session_state.live_streaming_outputs[fn_key_for_status] += f"\nUploading to GCS..." # Append to log
                                    storage_client_upload = storage.Client() # Client per upload attempt in thread
                                    bucket_upload = storage_client_upload.bucket(gcs_bucket_name_for_upload)
                                    # Use the new gcs_output_metadata_prefix_for_batch
                                    gcs_destination_blob_name = f"{gcs_output_metadata_prefix_for_batch}{output_txt_filename}"
                                    if not gcs_output_metadata_prefix_for_batch.endswith('/'):
                                        gcs_destination_blob_name = f"{gcs_output_metadata_prefix_for_batch}/{output_txt_filename}"
                                    blob_upload = bucket_upload.blob(gcs_destination_blob_name)
                                    blob_upload.upload_from_filename(local_output_path)
                                    st.session_state.batch_processed_files[fn_key_for_status] = "Success (Saved Locally & GCS)"
                                    st.session_state.live_streaming_outputs[fn_key_for_status] = f"Successfully saved locally and to GCS: gs://{gcs_bucket_name_for_upload}/{gcs_destination_blob_name}\n\n{full_response_text}"
                                    files_processed_successfully_count += 1
                                except Exception as e_gcs_upload:
                                    gcs_upload_error_msg = f"Error Uploading to GCS: {e_gcs_upload}"
                                    st.session_state.batch_processed_files[fn_key_for_status] = f"Success (Saved Locally), GCS Upload Failed: {gcs_upload_error_msg}"
                                    st.session_state.batch_processing_errors.append(f"Failed GCS upload for {fn_key_for_status}: {gcs_upload_error_msg}")
                                    st.session_state.live_streaming_outputs[fn_key_for_status] += f"\n--- ERROR GCS UPLOAD ---\n{gcs_upload_error_msg}"
                                    # If GCS upload is critical, this file now has an error associated with it.
                                    # files_with_errors_count += 1 # Uncomment if GCS upload failure means overall file error
                            except Exception as e_save:
                                save_error_msg = f"Error Saving File Locally: {e_save}"
                                st.session_state.batch_processed_files[fn_key_for_status] = save_error_msg
                                st.session_state.batch_processing_errors.append(f"Failed saving {fn_key_for_status} locally: {save_error_msg}")
                                st.session_state.live_streaming_outputs[fn_key_for_status] += f"\n--- ERROR SAVING LOCALLY ---\n{save_error_msg}"
                                files_with_errors_count +=1
                        else:
                            files_with_errors_count += 1
                except Exception as e_task:
                    error_detail = f"Error: Unhandled in API call - {e_task}"
                    if fn_key_for_status not in st.session_state.batch_processed_files or not st.session_state.batch_processed_files[fn_key_for_status].startswith("Error:"):
                         st.session_state.batch_processed_files[fn_key_for_status] = error_detail
                    st.session_state.batch_processing_errors.append(f"Failed processing {fn_key_for_status}: {e_task}")
                    st.session_state.live_streaming_outputs[fn_key_for_status] = f"--- FATAL TASK ERROR ---\n{error_detail}"
                    files_with_errors_count += 1
                finally:
                    completed_count_val = files_processed_successfully_count + files_with_errors_count
                    new_progress_value = int((completed_count_val / total_files) * 100) if total_files > 0 else 0
                    new_progress_text = f"File {completed_count_val}/{total_files} attempted. Progress: {new_progress_value}%"
                    
                    # Update session state for progress bar (Streamlit will pick this up on its next cycle)
                    st.session_state.batch_progress_value = new_progress_value
                    st.session_state.batch_progress_text = new_progress_text
                    # st.rerun() # Avoid reruns inside the async task loop for stability

            tasks.append(process_one_video(gcs_video_uri_item, video_filename_key, i, temp_local_video_path))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result_item in enumerate(results):
            if isinstance(result_item, Exception):
                fn_key_error = os.path.basename(selected_gcs_video_uris[i])
                print(f"Async task for {fn_key_error} failed with exception: {result_item}")
                # Ensure error is logged if not already caught by inner try-except
                if fn_key_error not in st.session_state.batch_processing_errors: # Avoid duplicate error logging
                    st.session_state.batch_processing_errors.append(f"Task for {fn_key_error} raised: {result_item}")
                if not st.session_state.batch_processed_files.get(fn_key_error, "").startswith("Error:"):
                    st.session_state.batch_processed_files[fn_key_error] = f"Error: Async task failed - {result_item}"


    try:
        asyncio.run(_process_batch_async())
    except RuntimeError as e:
        if "cannot be called when another loop is running" in str(e):
            st.session_state.batch_processing_errors.append(f"Asyncio loop error: {e}. Consider main thread async or nest_asyncio earlier.")
        else: raise
    finally:
        # Ensure batch_processing_errors list exists
        if 'batch_processing_errors' not in st.session_state:
            st.session_state.batch_processing_errors = []

        st.session_state.batch_progress_value = 100 # Mark as complete
        st.session_state.is_batch_processing = False
        st.session_state.batch_progress_text = "--- THREAD FINALLY BLOCK EXECUTED ---" # Distinct message for testing

        # The one print statement that seems to consistently work
        print(f"[DEBUG RERUN batch_process_metadata_threaded] About to sleep then call st.rerun() at end of batch_process_metadata_threaded finally block.", flush=True)
        time.sleep(0.1) # Small delay to allow state to propagate
        st.rerun()


def render_tab2(
    gcs_bucket_name_param: str, 
    gcs_prefix_param: str,
    gemini_ready: bool,
    # prompt_text_global: str, # This will be the default_prompt_template
    metadata_output_dir_global: str,
    gemini_api_key_global: str,
    ai_model_name_global: str, # Added
    concurrent_api_calls_limit: int,
    allowed_video_extensions_global: list,
    gcs_metadata_bucket_name: str,
    gcs_output_metadata_prefix_param: str # Added for GCS output path
):
    print(f"[DEBUG render_tab2 ENTRY] render_tab2 called. is_batch_processing: {st.session_state.get('is_batch_processing', 'Not Set')}") # NEW TOP LEVEL LOG
    if not st.session_state.get('is_batch_processing', True): # If False, meaning it *should* be showing results or initial state
        print(f"[DEBUG render_tab2 POST-BATCH] batch_processed_files: {st.session_state.get('batch_processed_files')}")
        print(f"[DEBUG render_tab2 POST-BATCH] live_streaming_outputs: {st.session_state.get('live_streaming_outputs')}")
        print(f"[DEBUG render_tab2 POST-BATCH] batch_processing_errors: {st.session_state.get('batch_processing_errors')}")
        print(f"[DEBUG render_tab2 POST-BATCH] batch_progress_text: {st.session_state.get('batch_progress_text')}")
    header_prefix = gcs_prefix_param if gcs_prefix_param else ""
    if header_prefix and not header_prefix.endswith('/'): header_prefix += '/'
    st.header(f"Step 2: Metadata Generation from GCS (gs://{gcs_bucket_name_param}/{header_prefix}*)")

    # Use the globally defined default_prompt_template for initialization
    if "batch_prompt_text_area_content" not in st.session_state: 
        st.session_state.batch_prompt_text_area_content = default_prompt_template 
    if "is_batch_processing" not in st.session_state: st.session_state.is_batch_processing = False
    if "batch_progress_text" not in st.session_state: st.session_state.batch_progress_text = ""
    if "batch_processed_files" not in st.session_state: st.session_state.batch_processed_files = {}
    if "batch_processing_errors" not in st.session_state: st.session_state.batch_processing_errors = []
    if "multiselect_gcs_videos_for_metadata" not in st.session_state: st.session_state.multiselect_gcs_videos_for_metadata = []
    if "batch_progress_value" not in st.session_state: st.session_state.batch_progress_value = 0
    if "batch_progress_bar_placeholder" not in st.session_state: st.session_state.batch_progress_bar_placeholder = None
    if "live_streaming_outputs" not in st.session_state: st.session_state.live_streaming_outputs = {}
    if "default_gcs_selection_applied" not in st.session_state: st.session_state.default_gcs_selection_applied = False

    gcs_video_uris = []
    error_listing_files = None
    if not gcs_bucket_name_param:
        error_listing_files = "GCS Bucket name for videos not provided."
        st.error(error_listing_files)
    else:
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(gcs_bucket_name_param)
            blobs = bucket.list_blobs(prefix=gcs_prefix_param if gcs_prefix_param else None)
            for blob_item in blobs:
                if any(blob_item.name.lower().endswith(ext) for ext in allowed_video_extensions_global):
                    uri = f"gs://{gcs_bucket_name_param}/{blob_item.name}"
                    gcs_video_uris.append(uri)
            gcs_video_uris.sort()
            if not gcs_video_uris: st.warning(f"No video files found in 'gs://{gcs_bucket_name_param}/{gcs_prefix_param or ''}'.")
        except Exception as e_list:
            error_listing_files = f"Error listing files from GCS (gs://{gcs_bucket_name_param}/{gcs_prefix_param or ''}): {e_list}"
            st.error(error_listing_files)

    if gcs_video_uris:
        st.success(f"Found {len(gcs_video_uris)} video file(s) in 'gs://{gcs_bucket_name_param}/{gcs_prefix_param or ''}'.")
        if not st.session_state.get('default_gcs_selection_applied', False) and gcs_video_uris:
            st.session_state.multiselect_gcs_videos_for_metadata = list(gcs_video_uris)
            st.session_state.default_gcs_selection_applied = True

        st.multiselect(
            "Select GCS Video Files for Metadata Generation:",
            options=gcs_video_uris,
            default=st.session_state.get("multiselect_gcs_videos_for_metadata", []),
            format_func=lambda x: os.path.basename(x),
            key="multiselect_gcs_videos_for_metadata"
        )
        
        current_batch_prompt_template_from_ui = st.text_area(
            "Gemini Prompt TEMPLATE (Placeholders {{actual_video_duration}} and {{source_filename}} will be replaced automatically):",
            value=st.session_state.batch_prompt_text_area_content, # This is the template
            height=300,
            key="batch_prompt_text_area_widget",
            on_change=lambda: setattr(st.session_state, 'batch_prompt_text_area_content', st.session_state.batch_prompt_text_area_widget)
        )

        if st.session_state.get("multiselect_gcs_videos_for_metadata"):
            if not gemini_ready or not gemini_api_key_global:
                st.warning("⚠️ Gemini API Key not configured.")
            elif not gcs_metadata_bucket_name:
                st.warning("⚠️ GCS bucket for metadata output not configured.")
            else:
                st.markdown("---")
                batch_process_button_disabled = st.session_state.get('is_batch_processing', False)
                if st.button("✨ Generate Metadata for Selected GCS Files", key="batch_process_gemini_button_gcs", disabled=batch_process_button_disabled):
                    st.session_state.is_batch_processing = True
                    st.session_state.batch_processed_files = {} 
                    st.session_state.batch_processing_errors = []
                    st.session_state.live_streaming_outputs = {}
                    # Initialize statuses for selected files
                    for gcs_uri_init in st.session_state.get("multiselect_gcs_videos_for_metadata", []):
                        fn_key_init = os.path.basename(gcs_uri_init)
                        st.session_state.batch_processed_files[fn_key_init] = f"Queued: {fn_key_init}"
                        st.session_state.live_streaming_outputs[fn_key_init] = "Queued..."
                    st.session_state.batch_progress_value = 0
                    st.session_state.batch_progress_text = "Starting batch processing..."
                    
                    # Ensure the latest template from UI is used
                    st.session_state.batch_prompt_text_area_content = current_batch_prompt_template_from_ui

                    uris_to_process = st.session_state.get("multiselect_gcs_videos_for_metadata", [])
                    if not uris_to_process:
                        st.error("No GCS video files selected for processing.")
                        st.session_state.is_batch_processing = False
                    else:
                        ctx = get_script_run_ctx()
                        thread = threading.Thread(
                            target=batch_process_metadata_threaded,
                            args=(
                                ctx, uris_to_process,
                                st.session_state.batch_prompt_text_area_content, # Pass the TEMPLATE from session state
                                metadata_output_dir_global,
                                gemini_api_key_global,
                                ai_model_name_global, # Added
                                concurrent_api_calls_limit,
                                gcs_metadata_bucket_name, # Maps to gcs_bucket_name_for_upload
                                gcs_output_metadata_prefix_param # Added, maps to gcs_output_metadata_prefix_for_batch
                            )
                        )
                        thread.start()
                        print(f"[DEBUG RERUN render_tab2] Calling st.rerun() after starting thread.") # LOG ADDED
                        st.rerun() 
    
    # ... (rest of render_tab2: progress bar, results display, clear button - should be mostly fine) ...
    elif not error_listing_files:
        st.info(f"No video files found in 'gs://{gcs_bucket_name_param}/{gcs_prefix_param or ''}'. Ensure files exist and bucket/prefix are correct.")

    if st.session_state.get('is_batch_processing', False) or st.session_state.get('batch_progress_value', 0) > 0 :
        if st.session_state.batch_progress_bar_placeholder is None:
            st.session_state.batch_progress_bar_placeholder = st.empty()
        current_progress = st.session_state.get('batch_progress_value', 0)
        current_text = st.session_state.get('batch_progress_text', "Initializing...")
        if st.session_state.batch_progress_bar_placeholder:
            st.session_state.batch_progress_bar_placeholder.progress(current_progress, text=current_text)
    elif st.session_state.batch_progress_bar_placeholder is not None:
        st.session_state.batch_progress_bar_placeholder.empty()
        st.session_state.batch_progress_bar_placeholder = None

    print(f"[DEBUG render_tab2 RESULTS_CHECK] is_batch_processing: {st.session_state.get('is_batch_processing', 'Not Set')}")
    print(f"[DEBUG render_tab2 RESULTS_CHECK] batch_processed_files exists: {'batch_processed_files' in st.session_state}")
    if 'batch_processed_files' in st.session_state:
        print(f"[DEBUG render_tab2 RESULTS_CHECK] batch_processed_files content: {st.session_state.batch_processed_files}")
    else:
        print(f"[DEBUG render_tab2 RESULTS_CHECK] batch_processed_files is empty or not set.")

    if not st.session_state.get('is_batch_processing', False) and st.session_state.get('batch_processed_files'):
        if st.session_state.get('batch_progress_bar_placeholder') is not None:
            st.session_state.batch_progress_bar_placeholder.empty()
            st.session_state.batch_progress_bar_placeholder = None
        st.markdown("---")
        st.subheader("Batch Processing Results:")
        final_batch_status_message = st.session_state.get('batch_progress_text', "Batch processing finished.")
        has_errors_final = "issue(s) encountered" in final_batch_status_message.lower() or \
                           any("error" in status.lower() for status in st.session_state.batch_processed_files.values())

        if has_errors_final:
            st.error(final_batch_status_message)
        else:
            st.success(final_batch_status_message)

        if st.session_state.get("batch_processing_errors"):
            with st.expander("Show Detailed Errors Log", expanded=False):
                for err_msg_item in st.session_state.batch_processing_errors: # Renamed err_msg
                    st.text(err_msg_item) # Using st.text for better formatting of multiline errors
        
        results_container = st.container()
        with results_container:
            sorted_filenames_res = sorted(st.session_state.get("batch_processed_files", {}).keys()) # Renamed
            for filename_key_results in sorted_filenames_res:
                status_res = st.session_state.batch_processed_files.get(filename_key_results, "Unknown status") # Renamed
                streamed_content_res = st.session_state.live_streaming_outputs.get(filename_key_results, "") # Renamed
                expander_label_status_res = status_res.split('(', 1)[0].split(':', 1)[0].strip() # Renamed
                expanded_default_res = ("Error" in status_res or \
                                   ("Success (Saved Locally & GCS)" not in status_res and \
                                    "Queued" not in status_res and \
                                    "Initiating" not in status_res and \
                                    "Processing" not in status_res and \
                                    "Uploading to GCS" not in status_res and \
                                    "Success (Saved Locally)" not in status_res
                                    )) # Renamed
                with st.expander(f"{filename_key_results} - Status: {expander_label_status_res}", expanded=expanded_default_res):
                    st.markdown(f"**Full Status:** `{status_res}`")
                    if streamed_content_res:
                        st.text_area("Generated Content/Log:", value=streamed_content_res, height=200, disabled=True, key=f"content_area_{filename_key_results}_results")
                    elif "Error" in status_res and not streamed_content_res :
                         st.caption("An error occurred before content generation, or content was not captured.")
                    if "Success (Saved Locally & GCS)" in status_res:
                        st.success(f"✅ Successfully processed and saved to GCS.")
                    elif "Success (Saved Locally)" in status_res and "GCS Upload Failed" in status_res:
                        st.warning(f"✅ Saved locally. ⚠️ GCS Upload Failed.") # Simpler message
                    elif "Error" in status_res:
                        st.error(f"❌ Error during processing.") # Simpler message
                    # ... other status messages

        if st.button("Clear Batch Results", key="clear_batch_results_button_gcs"):
            # ... (clear logic as before)
            st.session_state.batch_processed_files = {}
            st.session_state.batch_processing_errors = []
            st.session_state.batch_progress_text = ""
            st.session_state.batch_progress_value = 0
            st.session_state.live_streaming_outputs = {}
            if "multiselect_gcs_videos_for_metadata" in st.session_state:
                st.session_state.multiselect_gcs_videos_for_metadata = []
            st.session_state.default_gcs_selection_applied = False
            if st.session_state.get('batch_progress_bar_placeholder') is not None:
                st.session_state.batch_progress_bar_placeholder.empty()
                st.session_state.batch_progress_bar_placeholder = None
            st.session_state.is_batch_processing = False
            print(f"[DEBUG RERUN render_tab2] Calling st.rerun() after clearing batch results.")
            st.rerun()