import streamlit as st
import os
import re
import requests
import time
from google.cloud import storage
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

    # --- GCS Metadata File Listing ---
    st.subheader(f"Select Metadata File from gs://{gcs_bucket_name_param}/metadata/")
    metadata_gcs_prefix = "metadata/"
    gcs_metadata_files_options = ["-- Select a metadata file --"]
    
    if gcs_bucket_name_param:
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(gcs_bucket_name_param)
            actual_files = [b.name for b in bucket.list_blobs(prefix=metadata_gcs_prefix) if not b.name.endswith('/')]
            actual_files.sort()
            gcs_metadata_files_options.extend(actual_files)
        except Exception as e:
            st.error(f"Error listing metadata files from GCS: {e}")

    selected_metadata_file = st.selectbox(
        "Choose a metadata file to use for clip generation:",
        options=gcs_metadata_files_options,
        key="selectbox_gcs_metadata_file_tab3"
    )

    if selected_metadata_file and selected_metadata_file != "-- Select a metadata file --":
        st.success(f"Selected metadata file: `{selected_metadata_file}`")
        
        # In a real app, you might show a preview of the metadata here.
        # For now, we'll proceed directly to the generation step.

        st.markdown("---")
        st.subheader("AI Clip Selection (Optional)")
        ai_prompt = st.text_area(
            "Enter a prompt for the AI to select the best clips for a trailer:",
            value="Create a 90-second trailer focusing on the main conflict.",
            height=150,
            key="ai_clip_prompt_tab3"
        )

        output_gcs_prefix = st.text_input(
            "GCS Prefix for Output Clips:",
            value="clips/",
            key="output_gcs_prefix_tab3"
        )

        if st.button("✨ Generate Clips via API", key="generate_clips_button_tab3"):
            if not output_gcs_prefix:
                st.warning("Please provide a GCS prefix for the output clips.")
                return

            st.session_state.clips_job_id = None
            st.session_state.clips_job_status = "starting"
            st.session_state.clips_job_details = "Initializing clip generation job..."

            try:
                api_url = f"{API_BASE_URL}/generate-clips/"
                payload = {
                    "gcs_bucket": gcs_bucket_name_param,
                    "metadata_blob_name": selected_metadata_file,
                    "ai_prompt": ai_prompt,
                    "ai_model_name": st.session_state.get("AI_MODEL_NAME", "gemini-pro"), # Get from global config
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
                    status_placeholder.success(f"✅ **Job Complete:** {st.session_state.clips_job_details}")
                    st.session_state.clips_job_id = None
                    break
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

