import streamlit as st
import os
import re
import requests
import time
from services.gcs_service import generate_signed_url
from typing import Optional

# Define the base URL for the backend API
API_BASE_URL = "http://127.0.0.1:8000"

def render_tab3(gcs_bucket_name_param: str):
    st.header("Step 3: Clips Generation")

    # Initialize session state
    if "clips_job_id" not in st.session_state:
        st.session_state.clips_job_id = None
    if "clips_job_status" not in st.session_state:
        st.session_state.clips_job_status = None
    if "clips_job_details" not in st.session_state:
        st.session_state.clips_job_details = ""
    if "generated_clips_list" not in st.session_state:
        st.session_state.generated_clips_list = []

    # --- GCS Metadata File Listing ---
    st.subheader(f"Select Metadata Files from gs://{gcs_bucket_name_param}/metadata/")
    metadata_gcs_prefix = "metadata/"
    gcs_metadata_files = []
    
    if gcs_bucket_name_param:
        try:
            from services.gcs_service import get_storage_client
            storage_client = get_storage_client()
            bucket = storage_client.bucket(gcs_bucket_name_param)
            gcs_metadata_files = sorted([
                b.name for b in bucket.list_blobs(prefix=metadata_gcs_prefix)
                if not b.name.endswith('/') and b.name.lower().endswith('.json')
            ])
        except Exception as e:
            st.error(f"Error listing metadata files from GCS: {e}")

    if not gcs_metadata_files:
        st.warning(f"No metadata (.json) files found in 'gs://{gcs_bucket_name_param}/{metadata_gcs_prefix}'. Please generate metadata in Step 2.")
        return

    # Initialize or update selection state
    if 'metadata_selection' not in st.session_state:
        st.session_state.metadata_selection = {}

    current_selection = st.session_state.metadata_selection.copy()
    st.session_state.metadata_selection = {uri: current_selection.get(uri, False) for uri in gcs_metadata_files}

    # --- Selection Controls ---
    col1, col2, _ = st.columns([0.15, 0.15, 0.7])
    with col1:
        if st.button("Select All", key="select_all_metadata"):
            for uri in gcs_metadata_files:
                st.session_state.metadata_selection[uri] = True
            st.rerun()
    with col2:
        if st.button("Deselect All", key="deselect_all_metadata"):
            for uri in gcs_metadata_files:
                st.session_state.metadata_selection[uri] = False
            st.rerun()

    # --- Metadata File List with Checkboxes ---
    st.write("Choose metadata files to use for clip generation:")
    for uri in gcs_metadata_files:
        is_selected = st.checkbox(
            os.path.basename(uri),
            value=st.session_state.metadata_selection.get(uri, False),
            key=f"cb_meta_{uri}"
        )
        st.session_state.metadata_selection[uri] = is_selected

    selected_metadata_files = [uri for uri, selected in st.session_state.metadata_selection.items() if selected]

    if selected_metadata_files:
        st.success(f"Selected {len(selected_metadata_files)} metadata file(s).")
        
        st.markdown("---")
        output_gcs_prefix = st.text_input(
            "GCS Prefix for Output Clips:",
            value="clips/",
            key="output_gcs_prefix_tab3"
        )

        if st.button("✨ Generate Clips for Selected Files", key="generate_clips_button_tab3"):
            if not output_gcs_prefix:
                st.warning("Please provide a GCS prefix for the output clips.")
                return

            st.session_state.clips_job_id = None
            st.session_state.clips_job_status = "starting"
            st.session_state.clips_job_details = "Initializing clip generation job..."
            st.session_state.generated_clips_list = [] # Clear previous results

            try:
                api_url = f"{API_BASE_URL}/generate-clips/"
                payload = {
                    "gcs_bucket": gcs_bucket_name_param,
                    "metadata_blob_names": selected_metadata_files,
                    "output_gcs_prefix": output_gcs_prefix
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                st.session_state.clips_job_id = data.get("job_id")
                st.session_state.clips_job_status = "pending"
                st.success(f"Backend job for clip generation started! Job ID: {st.session_state.clips_job_id}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to start clip generation job. API connection error: {e}")
                st.session_state.clips_job_id = None

    # --- Job Status Polling ---
    if st.session_state.get("clips_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        
        job_id = st.session_state.clips_job_id
        status_placeholder = st.empty()
        
        while st.session_state.get("clips_job_status") in ["pending", "in_progress", "starting"]:
            try:
                status_url = f"{API_BASE_URL}/jobs/{job_id}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                st.session_state.clips_job_status = job_data.get("status")
                st.session_state.clips_job_details = job_data.get("details")

                if st.session_state.clips_job_status == "completed":
                    status_placeholder.success(f"✅ **Job Complete:** {job_data.get('details')}")
                    st.session_state.generated_clips_list = job_data.get("generated_clips", [])
                    st.session_state.clips_job_id = None
                    st.rerun()
                elif st.session_state.clips_job_status == "failed":
                    status_placeholder.error(f"❌ **Job Failed:** {st.session_state.clips_job_details}")
                    st.session_state.clips_job_id = None
                    break
                else:
                    status_placeholder.info(f"⏳ **In Progress:** {st.session_state.clips_job_details}")

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"Could not get job status. Connection error: {e}")
                break
            
            time.sleep(5)

    # --- Display Generated Clips ---
    if st.session_state.get("generated_clips_list"):
        st.markdown("---")
        st.subheader("✅ Generated Clips")

        # In a real app, you'd get these from a config or the API
        gcs_bucket_name = gcs_bucket_name_param

        for clip_blob_name in st.session_state.generated_clips_list:
            try:
                # This assumes gcs_service is available here or we call it differently
                # For simplicity, let's assume a helper function can be called
                # In a real app, you might need to adjust how you get the signed URL
                signed_url, error = generate_signed_url(gcs_bucket_name, clip_blob_name)
                
                if error:
                    st.error(f"Could not get URL for `{os.path.basename(clip_blob_name)}`: {error}")
                else:
                    st.video(signed_url)
                    st.caption(os.path.basename(clip_blob_name))

            except Exception as e:
                st.error(f"An error occurred while trying to display the video `{os.path.basename(clip_blob_name)}`: {e}")

        if st.button("Clear Generated Clips", key="clear_clips_button"):
            st.session_state.generated_clips_list = []
            st.rerun()

