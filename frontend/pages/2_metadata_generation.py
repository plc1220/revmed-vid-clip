import streamlit as st
import os
import time
import requests
import json
import pandas as pd
from utils import get_gcs_files
from utils import poll_job_status
from localization import get_translator

# Define the base URL for the backend API

# It's good to define it here so render_tab2 can use it as a default
# for st.session_state.batch_prompt_text_area_content
default_prompt_template = """
You are a professional film and drama editor AI, equipped with multimodal understanding (visuals, dialogue, sound, and inferred emotion). Your task is to meticulously analyze the provided video content from a drama series.** Your goal is to identify multiple key moments suitable for constructing a dynamic and engaging 2-minute trailer from **this specific clip.**

For each potential trailer moment you identify **within this video clip**, extract and structure the metadata. Be precise and insightful.

**Input to Analyze:**
*   **Primary:** The video content of the drama clip named **`{{source_filename}}`**. This clip is **`{{actual_video_duration}}`** long. Make sure you only capture scenes within the actual length of *this specific video clip*.
*   **Supplementary (if provided):** A transcript or scene-by-scene description. Your analysis should prioritize what is seen and heard in the video, using supplementary text to clarify or confirm dialogue and scene context if available.

**Prioritize Moments That:**
*   Introduce key characters effectively.
*   Establish the central conflict or mystery.
*   Contain strong emotional beats (joy, sorrow, anger, fear).
*   Feature visually compelling cinematography or action.
*   Include memorable or impactful lines of dialogue.
*   Create suspense or a cliffhanger.
*   Hint at a major plot twist or reveal.

**Your Task:**
Based on the video content and the prioritization criteria, identify the best moments and generate the corresponding metadata for each. The output format is handled by a JSON schema, so you only need to focus on the content of the analysis.

**CRITICAL GUARDRAIL:** The `timestamp_start_end` value is the most important field. It **MUST** be accurate. The end time of the clip cannot exceed the `actual_video_duration` of **`{{actual_video_duration}}`**. Any timestamp generated beyond this duration is invalid and will be discarded. Double-check your generated timestamps against the video's length before finalizing the output.

**Output Language:** Please generate the output in **{{language}}**.
"""

def toggle_video(video_uri):
    """Callback function to handle video checkbox state changes"""
    # Check the actual checkbox state from session_state
    checkbox_key = f"tab2_checkbox_{video_uri}"
    is_checked = st.session_state.get(checkbox_key, False)
    
    # Update the video selection state
    st.session_state.video_selection[video_uri] = is_checked

@st.cache_data
def load_metadata_content_tab2(gcs_bucket_name, gcs_blob_name):
    """Downloads and parses a metadata JSON file from GCS, with caching."""
    try:
        api_url = f"{st.session_state.API_BASE_URL}/gcs/download/{gcs_blob_name}"
        params = {"gcs_bucket": gcs_bucket_name}
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to download {gcs_blob_name}. Error: {e}")


# --- Render Metadata Generation Page ---
t = get_translator()
gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
workspace = st.session_state.workspace
segments_prefix = os.path.join(workspace, "segments/")
metadata_output_prefix = st.session_state.GCS_METADATA_PREFIX

# st.header(t("step2_header").format(bucket_name=gcs_bucket_name, prefix=segments_prefix))

# Initialize session state
if "metadata_job_id" not in st.session_state:
    st.session_state.metadata_job_id = None
if "metadata_job_status" not in st.session_state:
    st.session_state.metadata_job_status = None
if "metadata_job_details" not in st.session_state:
    st.session_state.metadata_job_details = ""
if "batch_prompt_text_area_content" not in st.session_state:
    st.session_state.batch_prompt_text_area_content = default_prompt_template
if "user_prompt" not in st.session_state:
    st.session_state.user_prompt = ""
if "batch_progress_bar_placeholder" not in st.session_state:
    st.session_state.batch_progress_bar_placeholder = None
if "generated_metadata_files" not in st.session_state:
    st.session_state.generated_metadata_files = []
if "viewed_metadata_content" not in st.session_state:
    st.session_state.viewed_metadata_content = {}

# --- GCS File Listing ---
gcs_video_uris = []
if not gcs_bucket_name:
    st.error(t("gcs_bucket_not_provided_error"))
else:
    blob_names = get_gcs_files(gcs_bucket_name, segments_prefix)
    gcs_video_uris = [f"gs://{gcs_bucket_name}/{name}" for name in blob_names]

    if not gcs_video_uris:
        st.warning(t("no_video_segments_warning").format(bucket_name=gcs_bucket_name, prefix=segments_prefix))

if gcs_video_uris:
    st.info(t("select_videos_for_metadata_label"), icon=":material/info:")
    # st.success(t("found_video_segments_success").format(count=len(gcs_video_uris)))

    # Initialize or update selection state
    if 'video_selection' not in st.session_state:
        st.session_state.video_selection = {}

    # Update state for current list of videos, preserving existing selections
    current_selection = st.session_state.video_selection.copy()
    st.session_state.video_selection = {uri: current_selection.get(uri, False) for uri in gcs_video_uris}
    
    # Clear checkbox states for videos that are no longer in the list
    for key in list(st.session_state.keys()):
        if key.startswith("tab2_checkbox_") and key not in [f"tab2_checkbox_{uri}" for uri in gcs_video_uris]:
            del st.session_state[key]

    # --- Selection Controls ---
    col1, col2, col3 = st.columns(3, gap="large")
    with col1:
        if st.button(t("select_all_button"), key="select_all_videos", use_container_width=True, icon=":material/check_circle:"):
            for uri in gcs_video_uris:
                st.session_state.video_selection[uri] = True
                # Update checkbox state
                st.session_state[f"tab2_checkbox_{uri}"] = True
            st.rerun()
    with col2:
        if st.button(t("deselect_all_button"), key="deselect_all_videos", use_container_width=True, icon=":material/close:"):
            for uri in gcs_video_uris:
                st.session_state.video_selection[uri] = False
                # Update checkbox state
                st.session_state[f"tab2_checkbox_{uri}"] = False
            st.rerun()
    with col3:
        if st.button(t("delete_selected_button"), key="delete_selected_videos", use_container_width=True, icon=":material/delete:"):
            selected_videos_to_delete = [uri for uri, selected in st.session_state.video_selection.items() if selected]
            if not selected_videos_to_delete:
                st.warning(t("no_videos_selected_for_deletion_warning"))
            else:
                try:
                    api_url = f"{st.session_state.API_BASE_URL}/gcs/delete-batch"
                    # Strip the "gs://<bucket_name>/" prefix to get the blob names
                    blob_names_to_delete = [uri.replace(f"gs://{gcs_bucket_name}/", "") for uri in selected_videos_to_delete]
                    
                    payload = {
                        "gcs_bucket": gcs_bucket_name,
                        "blob_names": blob_names_to_delete
                    }
                    response = requests.post(api_url, json=payload)
                    response.raise_for_status() # Will raise an exception for 4xx/5xx errors
                    
                    st.success(t("delete_success_message").format(count=len(blob_names_to_delete)))
                    
                    # Unselect the deleted files from the UI and clear checkbox states
                    for uri in selected_videos_to_delete:
                        if uri in st.session_state.video_selection:
                            st.session_state.video_selection[uri] = False
                        # Clear checkbox state
                        checkbox_key = f"tab2_checkbox_{uri}"
                        if checkbox_key in st.session_state:
                            st.session_state[checkbox_key] = False
                    
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(t("batch_deletion_api_error").format(e=e))
                except Exception as e:
                    st.error(t("unexpected_error").format(e=e))

    # --- Video List with Checkboxes ---
    for uri in gcs_video_uris:
        # The key must be unique, so we use the uri itself
        st.checkbox(
            os.path.basename(uri),
            key=f"tab2_checkbox_{uri}",
            on_change=toggle_video,
            args=(uri,)
        )

    # --- Prompt and Generate Button ---
    st.text_area(
        t("user_prompt_label"),
        value=st.session_state.user_prompt,
        height=100,
        key="user_prompt_widget",
        on_change=lambda: setattr(st.session_state, 'user_prompt', st.session_state.user_prompt_widget),
        help=t("user_prompt_help")
    )

    if st.sidebar.button(t("generate_metadata_button"), key="batch_process_gemini_button_gcs", use_container_width=True, type="primary", icon=":material/movie_info:"):
        selected_videos = [uri for uri, selected in st.session_state.video_selection.items() if selected]
        
        if not selected_videos:
            st.warning(t("no_videos_selected_warning"))
            st.stop()

        st.session_state.metadata_job_id = None
        st.session_state.metadata_job_status = "starting"
        st.session_state.metadata_job_details = "Initializing job..."
        st.session_state.generated_metadata_files = [] # Clear previous results
        st.session_state.viewed_metadata_content = {}

        try:
            api_url = f"{st.session_state.API_BASE_URL}/generate-metadata/"
            prompt_with_user_input = st.session_state.batch_prompt_text_area_content + "\n\n" + st.session_state.user_prompt
            
            # Get the current language from the session state, which is set in app.py
            language = st.session_state.get("selected_language", "English")

            payload = {
                "workspace": workspace,
                "gcs_bucket": gcs_bucket_name,
                "gcs_video_uris": selected_videos,
                "prompt_template": prompt_with_user_input,
                "ai_model_name": st.session_state.AI_MODEL_NAME,
                "gcs_output_prefix": metadata_output_prefix,
                "language": language
            }
            response = requests.post(api_url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            st.session_state.metadata_job_id = data.get("job_id")
            st.session_state.metadata_job_status = "pending"
            st.success(t("backend_job_start_success").format(job_id=st.session_state.metadata_job_id))

        except requests.exceptions.RequestException as e:
            st.error(t("metadata_job_start_error").format(e=e))
            st.session_state.metadata_job_id = None

# --- Job Status Polling ---
if st.session_state.get("metadata_job_id"):
    st.markdown("---")
    st.subheader(t("processing_status_subheader"))
    poll_job_status(st.session_state.metadata_job_id)
    st.session_state.metadata_job_id = None # Clear job
    st.rerun()

if st.session_state.get("generated_metadata_files"):
    st.markdown("---")
    st.subheader(t("generated_metadata_files_subheader"))

    for gcs_uri in st.session_state.generated_metadata_files:
        file_basename = os.path.basename(gcs_uri)
        with st.expander(t("view_metadata_expander").format(filename=file_basename)):
            try:
                gcs_path_str = gcs_uri.split("gs://")[1]
                gcs_bucket_name, gcs_blob_name = gcs_path_str.split('/', 1)
                metadata_content = load_metadata_content_tab2(gcs_bucket_name, gcs_blob_name)
                df = pd.DataFrame(metadata_content)
                st.dataframe(df)
            except Exception as e:
                st.error(t("load_metadata_error").format(filename=file_basename, e=e))

    if st.button(t("clear_results_button"), key="clear_metadata_results_button"):
        st.session_state.generated_metadata_files = []
        st.session_state.viewed_metadata_content = {}
        st.rerun()