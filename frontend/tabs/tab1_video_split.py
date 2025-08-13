import streamlit as st
import os
import requests
import time

# Define the base URL for the backend API

def render_tab1(allowed_video_extensions_param: list):
    st.header("Step 1: Video Split")

    st.info(
        "This tool now uses a backend service for robust video processing. "
        "Upload your video, and the system will handle the splitting in the background."
    )

    # Initialize session state variables for this tab
    if "split_job_id" not in st.session_state:
        st.session_state.split_job_id = None
    if "split_job_status" not in st.session_state:
        st.session_state.split_job_status = None
    if "split_job_details" not in st.session_state:
        st.session_state.split_job_details = ""

    # File uploader
    uploaded_file = st.file_uploader(
        "Upload a video file to split:",
        type=[ext.lstrip('.') for ext in allowed_video_extensions_param],
        key="uploaded_video_for_split_widget",
        help="Max file size: 1000MB"
    )
 
    if uploaded_file:
        st.write(f"Uploaded file: `{uploaded_file.name}` ({uploaded_file.size / (1024*1024):.2f} MB)")
        segment_duration_min = st.number_input("Max duration per chunk (minutes):", min_value=1, value=5, step=1, key="segment_duration_input")

        # We need to get the GCS bucket and blob name to send to the API.
        # For this refactor, we'll assume a default bucket from the main app's config
        # and that the file needs to be uploaded to GCS first.
        
        # This logic will be simplified. In a real app, the upload would be directly to GCS
        # or the API would handle the file upload. For now, we'll simulate the GCS upload step.
        
        gcs_bucket = st.session_state.get("GCS_BUCKET_NAME", "lc-ccob-test") # Get from global config
        gcs_blob_name = f"uploads/{uploaded_file.name}" # Example prefix

        if st.button("🚀 Upload and Start Splitting", key="split_video_button"):
            st.session_state.split_job_id = None
            st.session_state.split_job_status = None
            st.session_state.split_job_details = ""

            try:
                # Step 1: Upload the file to the backend, which then sends it to GCS
                with st.spinner(f"Uploading {uploaded_file.name} to the server..."):
                    upload_url = f"{st.session_state.API_BASE_URL}/upload-video/"
                    files = {'file': (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    data = {
                        'gcs_bucket': gcs_bucket,
                        'workspace': st.session_state.workspace
                    }
                    
                    upload_response = requests.post(upload_url, files=files, data=data)
                    upload_response.raise_for_status()
                    
                    upload_data = upload_response.json()
                    gcs_blob_name_from_api = upload_data["gcs_blob_name"]
                    st.success(f"File successfully uploaded to gs://{gcs_bucket}/{gcs_blob_name_from_api}")

                # Step 2: Start the splitting job with the now-uploaded file
                with st.spinner("Starting video splitting job..."):
                    split_url = f"{st.session_state.API_BASE_URL}/split-video/"
                    payload = {
                        "workspace": st.session_state.workspace,
                        "gcs_bucket": gcs_bucket,
                        "gcs_blob_name": gcs_blob_name_from_api,
                        "segment_duration": segment_duration_min * 60
                    }
                    split_response = requests.post(split_url, json=payload)
                    split_response.raise_for_status()

                    split_data = split_response.json()
                    st.session_state.split_job_id = split_data.get("job_id")
                    st.session_state.split_job_status = "pending"
                    st.success(f"Backend job started successfully! Job ID: {st.session_state.split_job_id}")
                    st.info("The video is being processed in the background. You can monitor the status below.")

            except requests.exceptions.RequestException as e:
                error_message = f"An API error occurred: {e}"
                if e.response:
                    error_message += f" - {e.response.text}"
                st.error(error_message)
                st.session_state.split_job_id = None
    else:
        st.info("Please upload a video file to enable splitting options.")

    # --- Job Status Polling ---
    if st.session_state.get("split_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        
        job_id = st.session_state.split_job_id
        status_placeholder = st.empty()
        
        while st.session_state.get("split_job_status") in ["pending", "in_progress"]:
            try:
                status_url = f"{st.session_state.API_BASE_URL}/jobs/{job_id}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                st.session_state.split_job_status = job_data.get("status")
                st.session_state.split_job_details = job_data.get("details")

                if st.session_state.split_job_status == "completed":
                    status_placeholder.success(f"✅ **Job Complete:** {st.session_state.split_job_details}")
                    st.session_state.split_job_id = None # Clear job so we can start another
                    break
                elif st.session_state.split_job_status == "failed":
                    status_placeholder.error(f"❌ **Job Failed:** {st.session_state.split_job_details}")
                    st.session_state.split_job_id = None # Clear job
                    break
                else:
                    status_placeholder.info(f"⏳ **In Progress:** {st.session_state.split_job_details}")

            except requests.exceptions.RequestException as e:
                status_placeholder.error(f"Could not get job status. Connection error: {e}")
                break # Stop polling on connection error
            
            time.sleep(2) # Poll every 5 seconds