import streamlit as st
import os
import re
import json
import requests
import time
import pandas as pd
from typing import Optional
from utils import poll_job_status

# Define the base URL for the backend API

@st.cache_data
def load_metadata_content(gcs_bucket_name, gcs_blob_name):
    """Downloads and parses a metadata JSON file from GCS, with caching."""
    try:
       # The new endpoint includes the blob name in the path, which avoids encoding issues.
       api_url = f"{st.session_state.API_BASE_URL}/gcs/download/{gcs_blob_name}"
       params = {"gcs_bucket": gcs_bucket_name}
       response = requests.get(api_url, params=params)
       response.raise_for_status()
       return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to download {gcs_blob_name}. Error: {e}")

def render_tab3():
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
    metadata_gcs_prefix = os.path.join(workspace, "metadata/")
    clips_output_prefix = st.session_state.GCS_OUTPUT_CLIPS_PREFIX

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
    st.subheader(f"Select Metadata Files from gs://{gcs_bucket_name}/{metadata_gcs_prefix}")
    gcs_metadata_files = []
    
    if gcs_bucket_name:
        try:
            api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
            params = {"gcs_bucket": gcs_bucket_name, "prefix": metadata_gcs_prefix}
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            gcs_metadata_files = response.json().get("files", [])
        except requests.exceptions.RequestException as e:
            st.error(f"Error listing metadata files from GCS: {e}")
            gcs_metadata_files = []

    if not gcs_metadata_files:
        st.warning(f"No metadata (.json) files found in 'gs://{gcs_bucket_name}/{metadata_gcs_prefix}'. Please generate metadata in Step 2.")
        return

    # Initialize or update selection state
    if 'metadata_selection' not in st.session_state:
        st.session_state.metadata_selection = {}

    current_selection = st.session_state.metadata_selection.copy()
    st.session_state.metadata_selection = {uri: current_selection.get(uri, False) for uri in gcs_metadata_files}

    # --- Selection Controls ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.55])
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
    with col3:
        if st.button("Delete Selected", key="delete_selected_metadata"):
            selected_metadata_to_delete = [uri for uri, selected in st.session_state.metadata_selection.items() if selected]
            if not selected_metadata_to_delete:
                st.warning("No metadata files selected for deletion.")
            else:
                try:
                    api_url = f"{st.session_state.API_BASE_URL}/gcs/delete-batch"
                    payload = {
                        "gcs_bucket": gcs_bucket_name,
                        "blob_names": selected_metadata_to_delete
                    }
                    response = requests.post(api_url, json=payload)
                    response.raise_for_status()
                    
                    deleted_files = response.json().get("deleted_files", [])
                    failed_files = response.json().get("failed_files", {})

                    if deleted_files:
                        st.success(f"Successfully deleted {len(deleted_files)} metadata file(s).")
                        load_metadata_content.clear()
                        # Unselect deleted files
                        for uri in deleted_files:
                            if uri in st.session_state.metadata_selection:
                                st.session_state.metadata_selection[uri] = False
                    
                    if failed_files:
                        for uri, error in failed_files.items():
                            st.error(f"Failed to delete {os.path.basename(uri)}: {error}")
                    
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(f"An API error occurred during batch deletion: {e}")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

    # --- Metadata File List with Checkboxes ---
    st.write("Choose metadata files to use for clip generation:")
    for uri in gcs_metadata_files:
        file_basename = os.path.basename(uri)
        with st.expander(file_basename):
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                is_selected = st.checkbox(
                    "Select for clip generation",
                    value=st.session_state.metadata_selection.get(uri, False),
                    key=f"cb_meta_{uri}"
                )
                st.session_state.metadata_selection[uri] = is_selected
            with col2:
                if st.button("Delete", key=f"delete_meta_{uri}"):
                    try:
                        api_url = f"{st.session_state.API_BASE_URL}/delete-gcs-blob/"
                        payload = {
                            "gcs_bucket": gcs_bucket_name,
                            "blob_name": uri
                        }
                        response = requests.delete(api_url, json=payload)
                        response.raise_for_status()
                        st.success(f"Deleted {file_basename}.")
                        # Clear the cache for the deleted file to ensure it's re-fetched if re-uploaded
                        load_metadata_content.clear()
                        st.rerun()
                    except requests.exceptions.RequestException as e:
                        st.error(f"Failed to delete {file_basename}. Error: {e}")

            # Display metadata content automatically using the cached function
            try:
                metadata_content = load_metadata_content(gcs_bucket_name, uri)
                df = pd.DataFrame(metadata_content)
                st.dataframe(df)
            except Exception as e:
                st.error(f"Could not load content for {file_basename}: {e}")

    selected_metadata_files = [uri for uri, selected in st.session_state.metadata_selection.items() if selected]

    if selected_metadata_files:
        st.success(f"Selected {len(selected_metadata_files)} metadata file(s).")
        
        st.markdown("---")
        output_gcs_prefix = st.text_input(
            "GCS Prefix for Output Clips:",
            value=clips_output_prefix,
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
                api_url = f"{st.session_state.API_BASE_URL}/generate-clips/"
                payload = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name,
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
        poll_job_status(st.session_state.clips_job_id)
        st.session_state.clips_job_id = None
        st.rerun()

    # --- Display Generated Clips ---
    if st.session_state.get("generated_clips_list"):
        st.markdown("---")
        st.subheader("✅ Generated Clips")

        # In a real app, you'd get these from a config or the API
        gcs_bucket_name = st.session_state.GCS_BUCKET_NAME

        for clip_blob_name in st.session_state.generated_clips_list:
            try:
                # This assumes gcs_service is available here or we call it differently
                # For simplicity, let's assume a helper function can be called
                # In a real app, you might need to adjust how you get the signed URL
                api_url = f"{st.session_state.API_BASE_URL}/gcs/signed-url"
                params = {"gcs_bucket": gcs_bucket_name, "blob_name": clip_blob_name}
                response = requests.get(api_url, params=params)
                if response.status_code == 200:
                    signed_url = response.json().get("url")
                    error = None
                else:
                    signed_url = None
                    error = response.text
                
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
    
