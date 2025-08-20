import streamlit as st
import os
import requests
from utils import poll_multiple_job_statuses

def render_tab4():
    st.header("Step 4: Refine Clips by Cast (Face Recognition)")

    workspace = st.session_state.workspace
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    clips_gcs_prefix = os.path.join(workspace, "clips/")

    st.subheader(f"Select Clips from gs://{gcs_bucket_name}/{clips_gcs_prefix}")

    # --- GCS Clip Listing ---
    try:
        api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
        params = {"gcs_bucket": gcs_bucket_name, "prefix": clips_gcs_prefix}
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        gcs_clips = response.json().get("files", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Error listing clips from GCS: {e}")
        gcs_clips = []

    if not gcs_clips:
        st.warning(f"No clips found in 'gs://{gcs_bucket_name}/{clips_gcs_prefix}'. Please generate clips in Step 3 first.")
        return

    if 'clip_selection' not in st.session_state:
        st.session_state.clip_selection = {}

    # Update state for current list of clips, preserving existing selections
    current_selection = st.session_state.clip_selection.copy()
    st.session_state.clip_selection = {uri: current_selection.get(uri, False) for uri in gcs_clips}

    # --- Selection Controls ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.55])
    with col1:
        if st.button("Select All", key="select_all_clips_frs"):
            for uri in gcs_clips:
                st.session_state.clip_selection[uri] = True
            st.rerun()
    with col2:
        if st.button("Deselect All", key="deselect_all_clips_frs"):
            for uri in gcs_clips:
                st.session_state.clip_selection[uri] = False
            st.rerun()
    with col3:
        if st.button("Delete Selected", key="delete_selected_clips_frs"):
            selected_clips_to_delete = [uri for uri, selected in st.session_state.clip_selection.items() if selected]
            if not selected_clips_to_delete:
                st.warning("No clips selected for deletion.")
            else:
                try:
                    api_url = f"{st.session_state.API_BASE_URL}/gcs/delete-batch"
                    payload = {
                        "gcs_bucket": gcs_bucket_name,
                        "blob_names": selected_clips_to_delete
                    }
                    response = requests.post(api_url, json=payload)
                    response.raise_for_status()
                    
                    deleted_files = response.json().get("deleted_files", [])
                    failed_files = response.json().get("failed_files", {})

                    if deleted_files:
                        st.success(f"Successfully deleted {len(deleted_files)} clip(s).")
                        # Unselect deleted files
                        for uri in deleted_files:
                            if uri in st.session_state.clip_selection:
                                st.session_state.clip_selection[uri] = False
                    
                    if failed_files:
                        for uri, error in failed_files.items():
                            st.error(f"Failed to delete {os.path.basename(uri)}: {error}")
                    
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(f"An API error occurred during batch deletion: {e}")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

    # --- Clip List with Checkboxes ---
    st.write("Select clips to process for face recognition:")
    for uri in gcs_clips:
        is_selected = st.checkbox(
            os.path.basename(uri),
            value=st.session_state.clip_selection.get(uri, False),
            key=f"cb_frs_{uri}"
        )
        st.session_state.clip_selection[uri] = is_selected


    # --- Cast Photo Uploader ---
    uploaded_cast_photos = st.file_uploader(
        "Upload photos of cast members (one face per photo)",
        accept_multiple_files=True,
        type=['.jpg', '.jpeg', '.png'],
        key="frs_uploader"
    )

    if st.button("✨ Refine Clips by Cast", key="refine_clip_by_face_button"):
        selected_clips = [uri for uri, selected in st.session_state.clip_selection.items() if selected]

        if not selected_clips:
            st.warning("Please select at least one clip to process.")
            return
        if not uploaded_cast_photos:
            st.warning("Please upload at least one photo of a cast member.")
            return

        # 1. Upload cast photos to a temporary location in GCS
        cast_photo_uris = []
        temp_photo_prefix = os.path.join(workspace, "temp_cast_photos/")
        
        for uploaded_file in uploaded_cast_photos:
            try:
                upload_url = f"{st.session_state.API_BASE_URL}/upload-cast-photo/"
                files = {'photo_file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                params = {
                    "gcs_bucket": gcs_bucket_name,
                    "workspace": workspace
                }
                
                response = requests.post(upload_url, files=files, params=params)
                response.raise_for_status()
                gcs_blob_name = response.json().get("gcs_blob_name")
                cast_photo_uris.append(f"gs://{gcs_bucket_name}/{gcs_blob_name}")
                st.info(f"Uploaded cast photo: {gcs_blob_name}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to upload {uploaded_file.name}. Error: {e.response.text if e.response else e}")
                return

        # 2. Start the face recognition job for each selected clip
        
        # For now, we trigger jobs one by one.
        # A better approach for the future would be to have a backend endpoint
        # that accepts a list of clips to process in a single batch job.
        
        st.session_state.refine_jobs = []
        
        for clip_uri in selected_clips:
            try:
                api_url = f"{st.session_state.API_BASE_URL}/generate-clips-by-face/"
                payload = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name,
                    "gcs_video_uri": clip_uri,
                    "gcs_cast_photo_uris": cast_photo_uris,
                    "output_gcs_prefix": os.path.join(workspace, "refined_clips/")
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                job_id = data.get("job_id")
                st.session_state.refine_jobs.append({"job_id": job_id, "clip": os.path.basename(clip_uri), "status": "pending"})
                st.success(f"Backend job for '{os.path.basename(clip_uri)}' started! Job ID: {job_id}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to start face recognition job for {os.path.basename(clip_uri)}. API error: {e.response.text if e.response else e}")
        
        if st.session_state.refine_jobs:
            st.rerun()

    # --- Job Status Polling ---
    if "refine_jobs" in st.session_state and st.session_state.refine_jobs:
        poll_multiple_job_statuses(st.session_state.refine_jobs)
