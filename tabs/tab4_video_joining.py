import streamlit as st
import os
import requests
import time
import datetime
from services.gcs_service import list_gcs_files, generate_signed_url

# Define the base URL for the backend API
API_BASE_URL = "http://127.0.0.1:8000"

def list_gcs_clips_for_display(bucket_name, prefix):
    """
    Lists clips and generates signed URLs for direct display in Streamlit.
    This remains in the UI as it's for presentation, not processing.
    """
    try:
        allowed_extensions = ['.mp4', '.mov', '.avi', '.mkv']
        blob_names, error = list_gcs_files(bucket_name, prefix, allowed_extensions)
        if error:
            return [], f"Error listing GCS clips: {error}"

        clips_data = []
        for blob_name in blob_names:
            url, error = generate_signed_url(bucket_name, blob_name)
            if error:
                print(f"Could not generate signed URL for {blob_name}: {error}")
                continue
            
            clips_data.append({
                "name": blob_name,
                "filename": os.path.basename(blob_name),
                "url": url
            })
        return clips_data, None
    except Exception as e:
        return [], f"Error processing GCS clips for display: {e}"

def render_tab4(gcs_bucket_name="your-gcs-bucket-name"):
    st.header("🎬 Video Stitcher")
    st.markdown("Select clips from GCS, then stitch them together into a new video.")

    # Initialize session state
    if 'selected_clips_for_joining' not in st.session_state:
        st.session_state.selected_clips_for_joining = []
    if 'join_job_id' not in st.session_state:
        st.session_state.join_job_id = None
    if 'join_job_status' not in st.session_state:
        st.session_state.join_job_status = None
    if 'join_job_details' not in st.session_state:
        st.session_state.join_job_details = ""

    clips_gcs_prefix = "clips/"
    joined_clips_gcs_prefix = "joined_clips/"

    clips_data, error = list_gcs_clips_for_display(gcs_bucket_name, clips_gcs_prefix)
    if error:
        st.error(error)
        return

    if not clips_data:
        st.info(f"No video clips found in GCS bucket '{gcs_bucket_name}' under prefix '{clips_gcs_prefix}'.")
        return

    st.subheader(f"Available Clips from gs://{gcs_bucket_name}/{clips_gcs_prefix}")
    
    # --- Clip Selection ---
    num_columns = st.slider("Number of columns for clip display:", 1, 5, 3)
    cols = st.columns(num_columns)
    
    currently_selected_names = [c['name'] for c in st.session_state.selected_clips_for_joining]
    
    for i, clip_info in enumerate(clips_data):
        with cols[i % num_columns]:
            st.video(clip_info["url"])
            is_selected = clip_info['name'] in currently_selected_names
            if st.checkbox(f"Select {clip_info['filename']}", value=is_selected, key=f"select_{clip_info['name']}"):
                if not is_selected:
                    st.session_state.selected_clips_for_joining.append(clip_info)
            else:
                if is_selected:
                    st.session_state.selected_clips_for_joining = [c for c in st.session_state.selected_clips_for_joining if c['name'] != clip_info['name']]

    # --- Display Order and Join Button ---
    if st.session_state.selected_clips_for_joining:
        st.subheader("Selected Clips (in order of joining):")
        ordered_filenames = [f"{idx+1}. {c['filename']}" for idx, c in enumerate(st.session_state.selected_clips_for_joining)]
        st.write(" -> ".join(ordered_filenames))

        if st.button("🎬 Stitch Selected Clips via API", key="join_videos_button"):
            st.session_state.join_job_id = None
            st.session_state.join_job_status = "starting"
            st.session_state.join_job_details = "Initializing video joining job..."

            try:
                api_url = f"{API_BASE_URL}/join-videos/"
                payload = {
                    "gcs_bucket": gcs_bucket_name,
                    "clip_blob_names": [c['name'] for c in st.session_state.selected_clips_for_joining],
                    "output_gcs_prefix": joined_clips_gcs_prefix
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                st.session_state.join_job_id = data.get("job_id")
                st.session_state.join_job_status = "pending"
                st.success(f"Backend job for joining videos started! Job ID: {st.session_state.join_job_id}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to start joining job. API connection error: {e}")
                st.session_state.join_job_id = None
    else:
        st.info("Select one or more clips to enable the stitching option.")

    # --- Job Status Polling ---
    if st.session_state.get("join_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        
        job_id = st.session_state.join_job_id
        status_placeholder = st.empty()
        
        while st.session_state.get("join_job_status") in ["pending", "in_progress", "starting"]:
            try:
                status_url = f"{API_BASE_URL}/jobs/{job_id}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                st.session_state.join_job_status = job_data.get("status")
                st.session_state.join_job_details = job_data.get("details")

                if st.session_state.join_job_status == "completed":
                    status_placeholder.success(f"✅ **Job Complete:** {st.session_state.join_job_details}")
                    st.session_state.join_job_id = None
                    # In a real app, you might add a link to the final video here
                    break
                elif st.session_state.join_job_status == "failed":
                    status_placeholder.error(f"❌ **Job Failed:** {st.session_state.join_job_details}")
                    st.session_state.join_job_id = None
                    break
                else:
                    status_placeholder.info(f"⏳ **In Progress:** {st.session_state.join_job_details}")

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"Could not get job status. Connection error: {e}")
                break
            
            time.sleep(5)