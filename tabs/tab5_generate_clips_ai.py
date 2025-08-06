import streamlit as st
import os
import requests
import time
from services.gcs_service import list_gcs_files

# Define the base URL for the backend API
API_BASE_URL = "http://127.0.0.1:8000"

def render_tab5(
    gemini_api_key_param: str,
    ai_model_name_param: str,
    gemini_ready_param: bool
):
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
    metadata_gcs_prefix = os.path.join(workspace, st.session_state.GCS_METADATA_PREFIX)
    output_clips_prefix = st.session_state.GCS_OUTPUT_CLIPS_PREFIX
    st.header("Step 5: Generate Clips with AI")

    # Initialize session state
    if "ai_clips_job_id" not in st.session_state:
        st.session_state.ai_clips_job_id = None
    if "ai_clips_job_status" not in st.session_state:
        st.session_state.ai_clips_job_status = None
    if "ai_clips_job_details" not in st.session_state:
        st.session_state.ai_clips_job_details = ""

    # --- GCS Metadata File Listing ---
    st.subheader(f"Select Metadata File from gs://{gcs_bucket_name}/{metadata_gcs_prefix}")
    gcs_metadata_files_options = ["-- Select a metadata file --"]
    
    if gcs_bucket_name:
        actual_files, error = list_gcs_files(
            gcs_bucket_name,
            metadata_gcs_prefix,
            allowed_extensions=['.json']
        )
        if error:
            st.error(f"Error listing metadata files from GCS: {error}")
        else:
            gcs_metadata_files_options.extend(actual_files)

    selected_metadata_file = st.selectbox(
        "Choose a metadata file to use for clip generation:",
        options=gcs_metadata_files_options,
        key="selectbox_gcs_metadata_file_tab5"
    )

    if selected_metadata_file and selected_metadata_file != "-- Select a metadata file --":
        st.success(f"Selected metadata file: `{selected_metadata_file}`")

        st.markdown("---")
        st.subheader("AI Clip Selection Prompt")
        ai_prompt = st.text_area(
            "Enter a prompt for the AI to select the best clips for a trailer:",
            value="Create a 90-second trailer focusing on the main conflict.",
            height=150,
            key="ai_clip_prompt_tab5"
        )

        if st.button("✨ Generate Clips with AI via API", key="generate_ai_clips_button"):
            st.session_state.ai_clips_job_id = None
            st.session_state.ai_clips_job_status = "starting"
            st.session_state.ai_clips_job_details = "Initializing AI clip generation job..."

            try:
                api_url = f"{API_BASE_URL}/generate-clips/"
                payload = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name,
                    "metadata_blob_names": [selected_metadata_file], # API expects a list
                    "output_gcs_prefix": output_clips_prefix
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                st.session_state.ai_clips_job_id = data.get("job_id")
                st.session_state.ai_clips_job_status = "pending"
                st.success(f"Backend job for AI clip generation started! Job ID: {st.session_state.ai_clips_job_id}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to start AI clip generation job. API connection error: {e}")
                st.session_state.ai_clips_job_id = None

    # --- Job Status Polling ---
    if st.session_state.get("ai_clips_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        
        job_id = st.session_state.ai_clips_job_id
        status_placeholder = st.empty()
        
        while st.session_state.get("ai_clips_job_status") in ["pending", "in_progress", "starting"]:
            try:
                status_url = f"{API_BASE_URL}/jobs/{job_id}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                st.session_state.ai_clips_job_status = job_data.get("status")
                st.session_state.ai_clips_job_details = job_data.get("details")

                if st.session_state.ai_clips_job_status == "completed":
                    status_placeholder.success(f"✅ **Job Complete:** {st.session_state.ai_clips_job_details}")
                    st.write("Debug Info: Full job data response")
                    st.json(job_data)
                    st.session_state.ai_clips_job_id = None
                    break
                elif st.session_state.ai_clips_job_status == "failed":
                    status_placeholder.error(f"❌ **Job Failed:** {st.session_state.ai_clips_job_details}")
                    st.session_state.ai_clips_job_id = None
                    break
                else:
                    status_placeholder.info(f"⏳ **In Progress:** {st.session_state.ai_clips_job_details}")

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"Could not get job status. Connection error: {e}")
                break
            
            time.sleep(5)