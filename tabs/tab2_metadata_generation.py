import streamlit as st
import os
import time
import requests
from google.cloud import storage

# Define the base URL for the backend API
API_BASE_URL = "http://127.0.0.1:8000"

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

def render_tab2(
    gcs_bucket_name_param: str,
    gcs_prefix_param: str,
    gemini_ready: bool,
    metadata_output_dir_global: str,
    gemini_api_key_global: str,
    ai_model_name_global: str,
    concurrent_api_calls_limit: int,
    allowed_video_extensions_global: list,
    gcs_metadata_bucket_name: str,
    gcs_output_metadata_prefix_param: str
):
    st.header(f"Step 2: Metadata Generation from Segment Folders (gs://{gcs_bucket_name_param}/segments/)")

    # Initialize session state
    if "metadata_job_id" not in st.session_state:
        st.session_state.metadata_job_id = None
    if "metadata_job_status" not in st.session_state:
        st.session_state.metadata_job_status = None
    if "metadata_job_details" not in st.session_state:
        st.session_state.metadata_job_details = ""
    if "batch_prompt_text_area_content" not in st.session_state:
        st.session_state.batch_prompt_text_area_content = default_prompt_template
    if "batch_progress_bar_placeholder" not in st.session_state:
        st.session_state.batch_progress_bar_placeholder = None
    if "processed_metadata_content" not in st.session_state:
        st.session_state.processed_metadata_content = None
    if "processed_metadata_filename" not in st.session_state:
        st.session_state.processed_metadata_filename = None

    # --- GCS Folder Listing ---
    gcs_video_uris = []
    segment_folders = []
    if not gcs_bucket_name_param:
        st.error("GCS Bucket name for videos not provided.")
    else:
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(gcs_bucket_name_param)
            # List blobs and infer directories from them
            blobs = bucket.list_blobs(prefix="segments/")
            folder_set = set()
            for blob in blobs:
                if any(blob.name.lower().endswith(ext) for ext in allowed_video_extensions_global):
                    folder_path = os.path.dirname(blob.name)
                    if folder_path:
                        folder_set.add(folder_path)
            segment_folders = sorted(list(folder_set))

            if not segment_folders:
                st.warning(f"No video segment folders found in 'gs://{gcs_bucket_name_param}/segments/'. Please split a video in Step 1.")
        except Exception as e:
            st.error(f"Error listing segment folders from GCS: {e}")

    if segment_folders:
        st.success(f"Found {len(segment_folders)} video segment folder(s).")

        selected_folder = st.selectbox(
            "Select a Video Segment Folder to Process:",
            options=segment_folders,
            key="selectbox_gcs_segment_folder"
        )

        if selected_folder:
            try:
                storage_client = storage.Client()
                bucket = storage_client.bucket(gcs_bucket_name_param)
                blobs = bucket.list_blobs(prefix=f"{selected_folder}/")
                for blob in blobs:
                    if any(blob.name.lower().endswith(ext) for ext in allowed_video_extensions_global):
                        gcs_video_uris.append(f"gs://{gcs_bucket_name_param}/{blob.name}")
                gcs_video_uris.sort()

                if gcs_video_uris:
                    st.write("The following video files will be processed for metadata generation:")
                    st.json([os.path.basename(uri) for uri in gcs_video_uris])
                else:
                    st.warning("No video files found in the selected folder.")
            except Exception as e:
                st.error(f"Error listing files from the selected GCS folder: {e}")
        
        st.text_area(
            "Gemini Prompt TEMPLATE:",
            value=st.session_state.batch_prompt_text_area_content,
            height=300,
            key="batch_prompt_text_area_widget",
            on_change=lambda: setattr(st.session_state, 'batch_prompt_text_area_content', st.session_state.batch_prompt_text_area_widget)
        )

        if st.button("✨ Generate Metadata via API", key="batch_process_gemini_button_gcs"):
            selected_videos = gcs_video_uris
            if not selected_videos:
                st.warning("No video files are selected or found in the chosen folder.")
                return

            st.session_state.metadata_job_id = None
            st.session_state.metadata_job_status = "starting"
            st.session_state.metadata_job_details = "Initializing job..."
            st.session_state.processed_metadata_content = None # Clear previous results
            st.session_state.processed_metadata_filename = None

            try:
                api_url = f"{API_BASE_URL}/generate-metadata/"
                payload = {
                    "gcs_bucket": gcs_bucket_name_param,
                    "gcs_video_uris": selected_videos,
                    "prompt_template": st.session_state.batch_prompt_text_area_content,
                    "ai_model_name": ai_model_name_global,
                    "gcs_output_prefix": gcs_output_metadata_prefix_param
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                st.session_state.metadata_job_id = data.get("job_id")
                st.session_state.metadata_job_status = "pending"
                st.success(f"Backend job for metadata generation started! Job ID: {st.session_state.metadata_job_id}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to start metadata job. API connection error: {e}")
                st.session_state.metadata_job_id = None

    # --- Job Status Polling ---
    if st.session_state.get("metadata_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        
        job_id = st.session_state.metadata_job_id
        status_placeholder = st.empty()
        
        while st.session_state.get("metadata_job_status") in ["pending", "in_progress", "starting"]:
            try:
                status_url = f"{API_BASE_URL}/jobs/{job_id}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                st.session_state.metadata_job_status = job_data.get("status")
                st.session_state.metadata_job_details = job_data.get("details")

                if st.session_state.metadata_job_status == "completed":
                    status_placeholder.success(f"✅ **Job Complete:** {st.session_state.metadata_job_details}")
                    try:
                        details_str = st.session_state.metadata_job_details
                        if "Consolidated metadata saved to" in details_str:
                            gcs_path_str = details_str.split("gs://")[1]
                            gcs_bucket_name, gcs_blob_name = gcs_path_str.split('/', 1)
                            storage_client = storage.Client()
                            bucket = storage_client.bucket(gcs_bucket_name)
                            blob = bucket.blob(gcs_blob_name)
                            metadata_content = blob.download_as_string()
                            st.session_state.processed_metadata_content = metadata_content.decode('utf-8')
                            st.session_state.processed_metadata_filename = os.path.basename(gcs_blob_name)
                    except Exception as e:
                        st.error(f"Failed to download result from GCS. Error: {e}")
                    st.session_state.metadata_job_id = None # Clear job
                    break
                elif st.session_state.metadata_job_status == "failed":
                    status_placeholder.error(f"❌ **Job Failed:** {st.session_state.metadata_job_details}")
                    st.session_state.metadata_job_id = None # Clear job
                    break
                else:
                    status_placeholder.info(f"⏳ **In Progress:** {st.session_state.metadata_job_details}")

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"Could not get job status. Connection error: {e}")
                break
            
            time.sleep(5)

    if st.session_state.get("processed_metadata_content"):
        st.markdown("---")
        st.subheader("✅ Consolidated Metadata Result")
        st.text_area(
            label=f"Downloaded from GCS: {st.session_state.get('processed_metadata_filename', 'N/A')}",
            value=st.session_state.processed_metadata_content,
            height=400,
            key="metadata_result_display"
        )
        if st.button("Clear Metadata Result", key="clear_metadata_result_button"):
            st.session_state.processed_metadata_content = None
            st.session_state.processed_metadata_filename = None
            st.rerun()