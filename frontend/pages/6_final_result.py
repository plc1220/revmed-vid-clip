import streamlit as st
import requests
import os
from localization import get_translator

def list_gcs_videos_via_api(bucket_name, prefix):
    """Lists videos in GCS via the backend API and gets signed URLs."""
    try:
        # List files
        api_url_list = f"{st.session_state.API_BASE_URL}/gcs/list"
        params_list = {"gcs_bucket": bucket_name, "prefix": prefix}
        response_list = requests.get(api_url_list, params=params_list)
        response_list.raise_for_status()
        blob_names = response_list.json().get("files", [])

        videos = []
        for blob_name in blob_names:
            if not blob_name.endswith(('.mp4', '.mov', '.avi')):
                continue

            # Get signed URL for each video
            api_url_signed = f"{st.session_state.API_BASE_URL}/gcs/signed-url"
            params_signed = {"gcs_bucket": bucket_name, "blob_name": blob_name}
            response_signed = requests.get(api_url_signed, params=params_signed)
            if response_signed.status_code == 200:
                url = response_signed.json().get("url")
                videos.append({"blob_name": blob_name, "url": url})
            else:
                st.warning(f"Could not get signed URL for {blob_name}")

        return videos
    except requests.exceptions.RequestException as e:
        # st.error(f"Error listing GCS videos via API: {e}")
        return []

def delete_gcs_videos_via_api(bucket_name, blob_names):
    """Deletes videos from GCS via the backend API."""
    try:
        api_url = f"{st.session_state.API_BASE_URL}/gcs/delete-batch"
        payload = {"gcs_bucket": bucket_name, "blob_names": blob_names}
        response = requests.post(api_url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error deleting GCS videos via API: {e}")
        return None


t = get_translator()
# st.title(t("final_result_title"))
# st.header(t("joined_clips_header"))

workspace = st.session_state.workspace
gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
joined_clips_prefix = os.path.join(workspace, "joined_clips/")

videos = list_gcs_videos_via_api(gcs_bucket_name, joined_clips_prefix)

if videos:
    selected_videos = []
    for i, video in enumerate(videos):
        col1, col2 = st.columns([0.1, 0.9])
        with col1:
            # Use a safer key based on the index to avoid issues with special characters in blob_name
            if st.checkbox("", key=f"final_video_{i}"):
                selected_videos.append(video["blob_name"])
        with col2:
            st.video(video["url"])

    if selected_videos:
        if st.button(t("delete_selected_button")):
            with st.spinner(t("deleting_videos_spinner")):
                result = delete_gcs_videos_via_api(gcs_bucket_name, selected_videos)
                if result:
                    st.success(t("delete_videos_success"))
                else:
                    st.error(t("delete_videos_error"))
else:
    st.info(t("no_joined_clips_info"))
