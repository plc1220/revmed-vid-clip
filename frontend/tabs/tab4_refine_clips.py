import streamlit as st
import os
import requests
from utils import poll_multiple_job_statuses
from localization import get_translator

def render_tab4():
    t = get_translator()
    st.header(t("step4_header"))

    workspace = st.session_state.workspace
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    clips_gcs_prefix = os.path.join(workspace, "clips/")

    st.subheader(t("select_clips_subheader").format(bucket_name=gcs_bucket_name, prefix=clips_gcs_prefix))

    # --- GCS Clip Listing ---
    try:
        api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
        params = {"gcs_bucket": gcs_bucket_name, "prefix": clips_gcs_prefix}
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        gcs_clips = response.json().get("files", [])
    except requests.exceptions.RequestException as e:
        # st.error(t("list_clips_error").format(e=e))
        gcs_clips = []

    if not gcs_clips:
        st.warning(t("no_clips_found_warning").format(bucket_name=gcs_bucket_name, prefix=clips_gcs_prefix))
        return

    if 'clip_selection' not in st.session_state:
        st.session_state.clip_selection = {}

    # Update state for current list of clips, preserving existing selections
    current_selection = st.session_state.clip_selection.copy()
    st.session_state.clip_selection = {uri: current_selection.get(uri, False) for uri in gcs_clips}

    # --- Selection Controls ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.55])
    with col1:
        if st.button(t("select_all_button"), key="select_all_clips_frs"):
            for uri in gcs_clips:
                st.session_state.clip_selection[uri] = True
            st.rerun()
    with col2:
        if st.button(t("deselect_all_button"), key="deselect_all_clips_frs"):
            for uri in gcs_clips:
                st.session_state.clip_selection[uri] = False
            st.rerun()
    with col3:
        if st.button(t("delete_selected_button"), key="delete_selected_clips_frs"):
            selected_clips_to_delete = [uri for uri, selected in st.session_state.clip_selection.items() if selected]
            if not selected_clips_to_delete:
                st.warning(t("no_clips_selected_for_deletion_warning"))
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
                        st.success(t("delete_clips_success").format(count=len(deleted_files)))
                        # Unselect deleted files
                        for uri in deleted_files:
                            if uri in st.session_state.clip_selection:
                                st.session_state.clip_selection[uri] = False
                    
                    if failed_files:
                        for uri, error in failed_files.items():
                            st.error(t("delete_clip_fail").format(filename=os.path.basename(uri), error=error))
                    
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(t("batch_deletion_api_error").format(e=e))
                except Exception as e:
                    st.error(t("unexpected_error").format(e=e))

    # --- Clip List with Checkboxes ---
    st.write(t("select_clips_for_face_recognition_label"))
    for uri in gcs_clips:
        is_selected = st.checkbox(
            os.path.basename(uri),
            value=st.session_state.clip_selection.get(uri, False),
            key=f"cb_frs_{uri}"
        )
        st.session_state.clip_selection[uri] = is_selected

    st.divider()
    st.subheader(t("refine_by_cast_subheader"))
    
    # Initialize session state for cast photos if it doesn't exist
    if 'uploaded_cast_photo_uris' not in st.session_state:
        st.session_state.uploaded_cast_photo_uris = []

    uploaded_cast_photos = st.file_uploader(
        t("upload_cast_photos_label"),
        accept_multiple_files=True,
        type=['jpg', 'jpeg', 'png'],
        key="cast_photos_uploader"
    )

    if uploaded_cast_photos:
        st.session_state.uploaded_cast_photo_uris = []
        for photo in uploaded_cast_photos:
            try:
                files = {
                    "photo_file": (photo.name, photo.getvalue(), photo.type)
                }
                data = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name
                }
                api_url = f"{st.session_state.API_BASE_URL}/upload-cast-photo"

                response = requests.post(api_url, data=data, files=files)
                response.raise_for_status()
                
                data = response.json()
                st.info(f"DEBUG: API Response for {photo.name}: {data}") # Temporary logging
                gcs_blob_name = data.get("gcs_blob_name")
                st.session_state.uploaded_cast_photo_uris.append(gcs_blob_name)
                st.success(f"Successfully uploaded {photo.name}")

            except requests.exceptions.RequestException as e:
                st.error(f"Failed to upload {photo.name}: {e.response.text if e.response else e}")

    if st.button(t("refine_clips_by_cast_button"), key="refine_clip_by_face_button"):
        selected_clips = [uri for uri, selected in st.session_state.clip_selection.items() if selected]

        if not selected_clips:
            st.warning(t("select_one_clip_warning"))
        elif not st.session_state.uploaded_cast_photo_uris:
            st.warning(t("upload_one_cast_photo_warning"))
            return
        
        # Start the face detection and copy job for each selected clip
        st.session_state.refine_jobs = []
        for clip_uri in selected_clips:
            try:
                api_url = f"{st.session_state.API_BASE_URL}/detect-faces-and-copy/"
                payload = {
                    "workspace": workspace,
                    "gcs_bucket": gcs_bucket_name,
                    "gcs_video_uri": clip_uri,
                    "output_gcs_prefix": os.path.join(workspace, "refined_clips/"),
                    "gcs_cast_photo_uris": st.session_state.uploaded_cast_photo_uris
                }
                response = requests.post(api_url, json=payload)
                response.raise_for_status()
                data = response.json()
                job_id = data.get("job_id")
                st.session_state.refine_jobs.append({"job_id": job_id, "clip": os.path.basename(clip_uri), "status": "pending"})
                st.success(t("backend_job_start_success").format(job_id=job_id))
            except requests.exceptions.RequestException as e:
                st.error(t("face_recognition_job_start_error").format(filename=os.path.basename(clip_uri), error=e.response.text if e.response else e))
        
        if st.session_state.refine_jobs:
            st.rerun()

    # --- Job Status Polling ---
    if "refine_jobs" in st.session_state and st.session_state.refine_jobs:
        poll_multiple_job_statuses(st.session_state.refine_jobs)
