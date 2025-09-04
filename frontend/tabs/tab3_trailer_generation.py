import streamlit as st
import os
import requests
import pandas as pd
from utils import poll_job_status
from localization import get_translator

# Define the base URL for the backend API

def load_metadata_content(gcs_bucket_name, gcs_blob_name):
    """Downloads and parses a metadata JSON file from GCS, with caching."""
    # Use session_state for manual caching
    if "metadata_cache" not in st.session_state:
        st.session_state.metadata_cache = {}

    if gcs_blob_name in st.session_state.metadata_cache:
        return st.session_state.metadata_cache[gcs_blob_name]

    try:
        # The new endpoint includes the blob name in the path, which avoids encoding issues.
        api_url = f"{st.session_state.API_BASE_URL}/gcs/download/{gcs_blob_name}"
        params = {"gcs_bucket": gcs_bucket_name}
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        content = response.json()
        st.session_state.metadata_cache[gcs_blob_name] = content
        return content
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to download {gcs_blob_name}. Error: {e}")

def render_tab3():
    t = get_translator()
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
    metadata_gcs_prefix = os.path.join(workspace, "metadata/")
    clips_output_prefix = st.session_state.GCS_OUTPUT_CLIPS_PREFIX

    st.header(t("step3_header"))

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
    st.subheader(t("select_metadata_files_subheader").format(bucket_name=gcs_bucket_name, prefix=metadata_gcs_prefix))
    gcs_metadata_files = []
    
    if gcs_bucket_name:
        try:
            api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
            params = {"gcs_bucket": gcs_bucket_name, "prefix": metadata_gcs_prefix}
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            gcs_metadata_files = response.json().get("files", [])
        except requests.exceptions.RequestException as e:
            gcs_metadata_files = []

    if not gcs_metadata_files:
        st.warning(t("no_metadata_files_warning").format(bucket_name=gcs_bucket_name, prefix=metadata_gcs_prefix))
        return

    # Initialize or update selection state
    if 'metadata_selection' not in st.session_state:
        st.session_state.metadata_selection = {}

    current_selection = st.session_state.metadata_selection.copy()
    st.session_state.metadata_selection = {uri: current_selection.get(uri, False) for uri in gcs_metadata_files}

    # --- Selection Controls ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.55])
    with col1:
        if st.button(t("select_all_button"), key="select_all_metadata"):
            for uri in gcs_metadata_files:
                st.session_state.metadata_selection[uri] = True
            st.rerun()
    with col2:
        if st.button(t("deselect_all_button"), key="deselect_all_metadata"):
            for uri in gcs_metadata_files:
                st.session_state.metadata_selection[uri] = False
            st.rerun()
    with col3:
        if st.button(t("delete_selected_button"), key="delete_selected_metadata"):
            selected_metadata_to_delete = [uri for uri, selected in st.session_state.metadata_selection.items() if selected]
            if not selected_metadata_to_delete:
                st.warning(t("no_metadata_selected_for_deletion_warning"))
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
                        st.success(t("delete_metadata_success").format(count=len(deleted_files)))
                        # Clear relevant entries from the manual cache
                        if "metadata_cache" in st.session_state:
                            for uri in deleted_files:
                                if uri in st.session_state.metadata_cache:
                                    del st.session_state.metadata_cache[uri]
                        
                        # Unselect deleted files
                        for uri in deleted_files:
                            if uri in st.session_state.metadata_selection:
                                st.session_state.metadata_selection[uri] = False
                    
                    if failed_files:
                        for uri, error in failed_files.items():
                            st.error(t("delete_metadata_fail").format(filename=os.path.basename(uri), error=error))
                    
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(t("batch_deletion_api_error").format(e=e))
                except Exception as e:
                    st.error(t("unexpected_error").format(e=e))

    # --- Metadata File List with Checkboxes ---
    st.write(t("choose_metadata_for_clips_label"))
    for uri in gcs_metadata_files:
        file_basename = os.path.basename(uri)
        with st.expander(file_basename):
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                is_selected = st.checkbox(
                    t("select_for_clip_generation_checkbox"),
                    value=st.session_state.metadata_selection.get(uri, False),
                    key=f"cb_meta_{uri}"
                )
                st.session_state.metadata_selection[uri] = is_selected
            with col2:
                if st.button(t("delete_button"), key=f"delete_meta_{uri}"):
                    try:
                        api_url = f"{st.session_state.API_BASE_URL}/delete-gcs-blob/"
                        payload = {
                            "gcs_bucket": gcs_bucket_name,
                            "blob_name": uri
                        }
                        response = requests.delete(api_url, json=payload)
                        response.raise_for_status()
                        st.success(t("delete_metadata_file_success").format(filename=file_basename))
                        # Clear the specific entry from the manual cache
                        if "metadata_cache" in st.session_state and uri in st.session_state.metadata_cache:
                            del st.session_state.metadata_cache[uri]
                        st.rerun()
                    except requests.exceptions.RequestException as e:
                        st.error(t("delete_metadata_file_error").format(filename=file_basename, e=e))

            # Display metadata content automatically using the cached function
            try:
                metadata_content = load_metadata_content(gcs_bucket_name, uri)
                df = pd.DataFrame(metadata_content)
                st.dataframe(df)
            except Exception as e:
                st.error(t("load_metadata_error").format(filename=file_basename, e=e))

    selected_metadata_files = [uri for uri, selected in st.session_state.metadata_selection.items() if selected]

    if selected_metadata_files:
        st.success(t("selected_metadata_files_success").format(count=len(selected_metadata_files)))
        
        st.markdown("---")
        output_gcs_prefix = st.text_input(
            t("output_gcs_prefix_label"),
            value=clips_output_prefix,
            key="output_gcs_prefix_tab3"
        )

        if st.button(t("generate_clips_button"), key="generate_clips_button_tab3"):
            if not output_gcs_prefix:
                st.warning(t("provide_gcs_prefix_warning"))
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
                st.success(t("backend_job_start_success").format(job_id=st.session_state.clips_job_id))

            except requests.exceptions.RequestException as e:
                st.error(t("clip_generation_job_start_error").format(e=e))
                st.session_state.clips_job_id = None

    # --- Job Status Polling ---
    if st.session_state.get("clips_job_id"):
        st.markdown("---")
        st.subheader(t("processing_status_subheader"))
        poll_job_status(st.session_state.clips_job_id)
        st.session_state.clips_job_id = None
        st.rerun()

    # --- Display Generated Clips ---
    if st.session_state.get("generated_clips_list"):
        st.markdown("---")
        st.subheader(t("generated_clips_subheader"))

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
                    st.error(t("get_clip_url_error").format(filename=os.path.basename(clip_blob_name), error=error))
                else:
                    st.video(signed_url)
                    st.caption(os.path.basename(clip_blob_name))

            except Exception as e:
                st.error(t("display_video_error").format(filename=os.path.basename(clip_blob_name), e=e))

        if st.button(t("clear_generated_clips_button"), key="clear_clips_button"):
            st.session_state.generated_clips_list = []
            st.rerun()
    
