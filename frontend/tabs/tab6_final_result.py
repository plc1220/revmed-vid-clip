import streamlit as st
import requests
import os

def list_gcs_videos_via_api(bucket_name, prefix):
    """Lists videos in GCS via the backend API and gets signed URLs."""
    try:
        # List files
        api_url_list = f"{st.session_state.API_BASE_URL}/gcs/list"
        params_list = {"gcs_bucket": bucket_name, "prefix": prefix}
        response_list = requests.get(api_url_list, params=params_list)
        response_list.raise_for_status()
        blob_names = response_list.json().get("files", [])

        video_urls = []
        for blob_name in blob_names:
            if not blob_name.endswith(('.mp4', '.mov', '.avi')):
                continue

            # Get signed URL for each video
            api_url_signed = f"{st.session_state.API_BASE_URL}/gcs/signed-url"
            params_signed = {"gcs_bucket": bucket_name, "blob_name": blob_name}
            response_signed = requests.get(api_url_signed, params=params_signed)
            if response_signed.status_code == 200:
                url = response_signed.json().get("url")
                video_urls.append(url)
            else:
                st.warning(f"Could not get signed URL for {blob_name}")

        return video_urls
    except requests.exceptions.RequestException as e:
        st.error(f"Error listing GCS videos via API: {e}")
        return []

def show():
    st.title("Final Result")
    st.header("Joined Clips")

    workspace = st.session_state.workspace
    gcs_bucket_name = st.session_state.GCS_BUCKET_NAME
    joined_clips_prefix = os.path.join(workspace, "joined_clips/")

    video_urls = list_gcs_videos_via_api(gcs_bucket_name, joined_clips_prefix)

    if video_urls:
        for video_url in video_urls:
            st.video(video_url)
    else:
        st.info("No joined clips found.")
