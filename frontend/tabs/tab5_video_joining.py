import streamlit as st
import os
import requests
import time
import datetime
import re
from utils import poll_job_status
from localization import get_translator

def format_duration(seconds):
    """Format duration in seconds to HH:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return {"hours": hours, "minutes": minutes, "seconds": secs}

def calculate_total_duration(selected_clips):
    """Calculate total duration of selected clips"""
    if not selected_clips:
        return 0
    return sum(clip.get('duration', 0) for clip in selected_clips)

def extract_duration_from_blob_name(blob_name):
    """Extract duration from blob name using regex pattern _{clip_duration:.3f}s.mp4"""
    # Pattern to match _{duration}s.mp4 format
    pattern = r'_(\d+\.\d{3})s\.mp4$'
    match = re.search(pattern, blob_name)
    if match:
        return float(match.group(1))
    return 0.0

# Define the base URL for the backend API
def list_gcs_clips_for_display(bucket_name, prefix):
    """
    Lists clips and generates signed URLs for direct display in Streamlit.
    This remains in the UI as it's for presentation, not processing.
    """
    try:
        api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
        params = {"gcs_bucket": bucket_name, "prefix": prefix}
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        blob_names = response.json().get("files", [])

        clips_data = []
        for blob_name in blob_names:
            api_url = f"{st.session_state.API_BASE_URL}/gcs/signed-url"
            params = {"gcs_bucket": bucket_name, "blob_name": blob_name}
            response = requests.get(api_url, params=params)
            if response.status_code == 200:
                url = response.json().get("url")
                duration = extract_duration_from_blob_name(blob_name)
                clips_data.append({
                    "name": blob_name,
                    "filename": os.path.basename(blob_name),
                    "url": url,
                    "duration": duration
                })
            else:
                print(f"Could not generate signed URL for {blob_name}: {response.text}")
                continue
        return clips_data, None
    except requests.exceptions.RequestException as e:
        return [], f"Error processing GCS clips for display: {e}"

def render_tab5():
    t = get_translator()
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
    st.header(t("step5_header"))
    st.markdown(t("step5_subheader"))

    # Initialize session state
    if 'selected_clips_for_joining' not in st.session_state:
        st.session_state.selected_clips_for_joining = []
    if 'join_job_id' not in st.session_state:
        st.session_state.join_job_id = None
    if 'join_job_status' not in st.session_state:
        st.session_state.join_job_status = None
    if 'join_job_details' not in st.session_state:
        st.session_state.join_job_details = ""

    # --- Source Selection ---
    st.subheader(t("select_clip_source_subheader"))
    # Use non-translated keys for logic
    source_keys = {
        "original_clips": os.path.join(workspace, "clips/"),
        "refined_clips": os.path.join(workspace, "refined_clips/")
    }
    
    # Translate keys for display
    source_options_display = {
        t("original_clips_option"): "original_clips",
        t("refined_clips_option"): "refined_clips"
    }
    
    if 'clip_source_key' not in st.session_state:
        st.session_state.clip_source_key = "original_clips" # Default to the key

    def on_source_change():
        # The widget's key holds the *display value*, so we need to find the corresponding internal key
        display_value = st.session_state.clip_source_selector
        st.session_state.clip_source_key = source_options_display[display_value]
        st.session_state.selected_clips_for_joining = [] # Clear selection on source change

    # We need to find the current display value that corresponds to our stored key
    current_display_value = [k for k, v in source_options_display.items() if v == st.session_state.clip_source_key][0]
    
    st.selectbox(
        t("choose_clip_folder_label"),
        options=source_options_display.keys(),
        index=list(source_options_display.keys()).index(current_display_value),
        key="clip_source_selector",
        on_change=on_source_change
    )

    # Use the stored key to get the correct path
    clips_gcs_prefix = source_keys[st.session_state.clip_source_key]
    
    joined_clips_gcs_prefix = "joined_clips/" # This can remain global or be namespaced too

    st.markdown("---")
    st.subheader(t("select_clips_to_join_subheader"))
    clips_data, error = list_gcs_clips_for_display(gcs_bucket_name, clips_gcs_prefix)
    if error:
        st.error(t("display_gcs_clips_error").format(e=error))
        return

    if not clips_data:
        st.info(t("no_clips_in_gcs_info").format(bucket_name=gcs_bucket_name, prefix=clips_gcs_prefix))
        return

    st.subheader(t("available_clips_subheader").format(bucket_name=gcs_bucket_name, prefix=clips_gcs_prefix))
    
    # --- Clip Selection ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.5])
    with col1:
        if st.button(t("select_all_button"), key="select_all_clips_joining"):
            st.session_state.selected_clips_for_joining = clips_data.copy()
            st.rerun()
    with col2:
        if st.button(t("deselect_all_button"), key="deselect_all_clips_joining"):
            st.session_state.selected_clips_for_joining = []
            st.rerun()
    with col3:
        if st.button(t("delete_selected_button"), key="delete_selected_clips_joining"):
            if st.session_state.selected_clips_for_joining:
                errors = []
                for clip in st.session_state.selected_clips_for_joining:
                    try:
                        api_url = f"{st.session_state.API_BASE_URL}/delete-gcs-blob/"
                        payload = {
                            "gcs_bucket": gcs_bucket_name,
                            "blob_name": clip['name']
                        }
                        response = requests.delete(api_url, json=payload)
                        response.raise_for_status()
                    except requests.exceptions.RequestException as e:
                        errors.append(t("delete_selected_clips_error").format(filename=clip['filename'], e=e))
                
                if errors:
                    st.error("\\n".join(errors))
                else:
                    st.success(t("delete_all_selected_clips_success"))
                
                st.session_state.selected_clips_for_joining = []
                st.rerun()

    num_columns = st.slider(t("columns_for_display_slider"), 1, 5, 3)
    cols = st.columns(num_columns)
    
    currently_selected_names = [c['name'] for c in st.session_state.selected_clips_for_joining]
    
    for i, clip_info in enumerate(clips_data):
        with cols[i % num_columns]:
            st.video(clip_info["url"])
            is_selected = clip_info['name'] in currently_selected_names

            c1, c2 = st.columns([0.8, 0.2])
            with c1:
                if st.checkbox(t("select_checkbox").format(filename=clip_info['filename']), value=is_selected, key=f"select_{clip_info['name']}"):
                    if not is_selected:
                        st.session_state.selected_clips_for_joining.append(clip_info)
                else:
                    if is_selected:
                        st.session_state.selected_clips_for_joining = [c for c in st.session_state.selected_clips_for_joining if c['name'] != clip_info['name']]
            with c2:
                if st.button("🗑️", key=f"delete_clip_{clip_info['name']}", help=t("delete_clip_button_help").format(filename=clip_info['filename'])):
                    try:
                        api_url = f"{st.session_state.API_BASE_URL}/delete-gcs-blob/"
                        payload = {
                            "gcs_bucket": gcs_bucket_name,
                            "blob_name": clip_info['name']
                        }
                        response = requests.delete(api_url, json=payload)
                        response.raise_for_status()
                        # Also remove from selection if it was selected
                        st.session_state.selected_clips_for_joining = [c for c in st.session_state.selected_clips_for_joining if c['name'] != clip_info['name']]
                        st.success(t("delete_single_clip_success").format(filename=clip_info['filename']))
                        st.rerun()
                    except requests.exceptions.RequestException as e:
                        st.error(t("delete_single_clip_error").format(filename=clip_info['filename'], e=e))

    # --- Display Order and Join Button ---
    with st.sidebar:
        if st.session_state.selected_clips_for_joining:
            st.subheader(t("selected_clips_subheader"))
            ordered_filenames = [f"{idx+1}. {c['filename']}" for idx, c in enumerate(st.session_state.selected_clips_for_joining)]
            st.write(" -> ".join(ordered_filenames))
            
            # Display total duration
            total_duration_seconds = calculate_total_duration(st.session_state.selected_clips_for_joining)
            duration_formatted = format_duration(total_duration_seconds)
            duration_text = t("total_duration_format").format(**duration_formatted)
            
            st.subheader(t("total_duration_label"))
            st.write( duration_text)

    if st.session_state.selected_clips_for_joining:
        if st.sidebar.button(t("stitch_clips_button"), key="join_videos_button"):
            st.session_state.join_job_id = None
            st.session_state.join_job_status = "starting"
            st.session_state.join_job_details = "Initializing video joining job..."

            try:
                api_url = f"{st.session_state.API_BASE_URL}/join-videos/"
                payload = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name,
                    "clip_blob_names": [c['name'] for c in st.session_state.selected_clips_for_joining],
                    "output_gcs_prefix": joined_clips_gcs_prefix
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                st.session_state.join_job_id = data.get("job_id")
                st.session_state.join_job_status = "pending"
                st.success(t("backend_job_start_success").format(job_id=st.session_state.join_job_id))

            except requests.exceptions.RequestException as e:
                st.error(t("video_joining_job_start_error").format(e=e))
                st.session_state.join_job_id = None
    else:
        st.info(t("select_clips_to_stitch_info"))

    # --- Job Status Polling ---
    if st.session_state.get("join_job_id"):
        st.markdown("---")
        st.subheader(t("processing_status_subheader"))
        poll_job_status(st.session_state.join_job_id)
        st.session_state.join_job_id = None