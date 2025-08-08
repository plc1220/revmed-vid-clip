import streamlit as st
import os
import requests
import time
import datetime

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
                clips_data.append({
                    "name": blob_name,
                    "filename": os.path.basename(blob_name),
                    "url": url
                })
            else:
                print(f"Could not generate signed URL for {blob_name}: {response.text}")
                continue
        return clips_data, None
    except requests.exceptions.RequestException as e:
        return [], f"Error processing GCS clips for display: {e}"

def render_tab4():
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
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

    clips_gcs_prefix = os.path.join(workspace, "clips/")
    joined_clips_gcs_prefix = "joined_clips/" # This can remain global or be namespaced too

    clips_data, error = list_gcs_clips_for_display(gcs_bucket_name, clips_gcs_prefix)
    if error:
        st.error(error)
        return

    if not clips_data:
        st.info(f"No video clips found in GCS bucket '{gcs_bucket_name}' under prefix '{clips_gcs_prefix}'.")
        return

    st.subheader(f"Available Clips from gs://{gcs_bucket_name}/{clips_gcs_prefix}")
    
    # --- Clip Selection ---
    col1, col2, col3, _ = st.columns([0.15, 0.15, 0.2, 0.5])
    with col1:
        if st.button("Select All", key="select_all_clips_joining"):
            st.session_state.selected_clips_for_joining = clips_data.copy()
            st.rerun()
    with col2:
        if st.button("Deselect All", key="deselect_all_clips_joining"):
            st.session_state.selected_clips_for_joining = []
            st.rerun()
    with col3:
        if st.button("Delete Selected", key="delete_selected_clips_joining"):
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
                        errors.append(f"Failed to delete {clip['filename']}. Error: {e}")
                
                if errors:
                    st.error("\\n".join(errors))
                else:
                    st.success("All selected clips deleted successfully.")
                
                st.session_state.selected_clips_for_joining = []
                st.rerun()

    num_columns = st.slider("Number of columns for clip display:", 1, 5, 3)
    cols = st.columns(num_columns)
    
    currently_selected_names = [c['name'] for c in st.session_state.selected_clips_for_joining]
    
    for i, clip_info in enumerate(clips_data):
        with cols[i % num_columns]:
            st.video(clip_info["url"])
            is_selected = clip_info['name'] in currently_selected_names

            c1, c2 = st.columns([0.8, 0.2])
            with c1:
                if st.checkbox(f"Select {clip_info['filename']}", value=is_selected, key=f"select_{clip_info['name']}"):
                    if not is_selected:
                        st.session_state.selected_clips_for_joining.append(clip_info)
                else:
                    if is_selected:
                        st.session_state.selected_clips_for_joining = [c for c in st.session_state.selected_clips_for_joining if c['name'] != clip_info['name']]
            with c2:
                if st.button("🗑️", key=f"delete_clip_{clip_info['name']}", help=f"Delete {clip_info['filename']}"):
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
                        st.success(f"Deleted {clip_info['filename']}.")
                        st.rerun()
                    except requests.exceptions.RequestException as e:
                        st.error(f"Failed to delete {clip_info['filename']}. Error: {e}")

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
                status_url = f"{st.session_state.API_BASE_URL}/jobs/{job_id}"
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