import streamlit as st
import streamlit.components.v1 as components
import os
import requests
import time
from utils import poll_job_status


def gcs_direct_uploader(api_base_url: str, gcs_bucket: str, workspace: str):
    """
    Renders a custom Streamlit component for direct-to-GCS file uploads.
    The component handles file selection and upload on the client-side and
    returns the GCS blob name to the Streamlit app upon completion.

    Args:
        api_base_url: The base URL of the backend API to get the signed URL.
        gcs_bucket: The GCS bucket to upload the file to.
        workspace: The workspace name to be passed to the backend.

    Returns:
        A dictionary with upload details if successful, otherwise None.
    """
    # Construct the paths to the component files
    component_path = os.path.join(os.path.dirname(__file__), "..", "components")
    html_path = os.path.join(component_path, "gcs_uploader.html")
    css_path = os.path.join(component_path, "gcs_uploader.css")
    js_path = os.path.join(component_path, "gcs_uploader.js")

    # Read the content of the files
    with open(html_path, "r") as f:
        html_template = f.read()
    with open(css_path, "r") as f:
        css_content = f.read()
    with open(js_path, "r") as f:
        js_content = f.read()

    # Inject CSS and JS into the HTML template
    html_template = html_template.replace(
        '<link rel="stylesheet" href="gcs_uploader.css">',
        f"<style>{css_content}</style>"
    )
    html_template = html_template.replace(
        '<script src="gcs_uploader.js"></script>',
        f"<script>{js_content}</script>"
    )

    # Set the data attributes on the body tag
    html_template = html_template.replace(
        '<body>',
        f'<body data-api-base-url="{api_base_url}" data-gcs-bucket="{gcs_bucket}" data-workspace="{workspace}">'
    )

    component_value = components.html(html_template, height=150)
    return component_value


def get_uploaded_videos(bucket_name, workspace):

    uploads_prefix = os.path.join(workspace, "uploads/")
    api_url = f"{st.session_state.API_BASE_URL}/gcs/list"
    params = {"gcs_bucket": bucket_name, "prefix": uploads_prefix}
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        blob_names = response.json().get("files", [])
    except:
        blob_names = []
    return blob_names


def render_tab1(allowed_video_extensions_param: list):
    st.header("Step 1: Video Split")

    gcs_bucket = st.session_state.GCS_BUCKET_NAME
    workspace = st.session_state.workspace
    uploaded_videos = get_uploaded_videos(gcs_bucket, workspace)

    if not uploaded_videos:
        st.warning("No uploaded videos found in the workspace. Please upload a video first.", icon=":material/warning:")
    else:
        st.info("Select one of the uploaded videos to proceed, or upload a new video", icon=":material/info:")
    
    st.subheader("Upload a new video")
    gcs_direct_uploader(
        api_base_url=st.session_state.API_BASE_URL, gcs_bucket=gcs_bucket, workspace=st.session_state.workspace
    )

    st.subheader("Select a video to split")
    gcs_blob_name = st.selectbox("Select a video:", get_uploaded_videos(gcs_bucket, workspace))

    # Initialize session state variables for splitting job
    if "split_job_id" not in st.session_state:
        st.session_state.split_job_id = None
    if "split_job_status" not in st.session_state:
        st.session_state.split_job_status = None
    if "split_job_details" not in st.session_state:
        st.session_state.split_job_details = ""

    segment_duration_min = st.number_input(
        "Max duration per chunk (minutes):", min_value=1, value=5, step=1, key="segment_duration_input"
    )

    if st.button("🚀 Start Splitting Job", key="start_split_job_button"):
        st.session_state.split_job_id = None
        st.session_state.split_job_status = None
        st.session_state.split_job_details = ""

        try:
            with st.spinner("Starting video splitting job..."):
                split_url = f"{st.session_state.API_BASE_URL}/split-video/"
                payload = {
                    "workspace": st.session_state.workspace,
                    "gcs_bucket": gcs_bucket,
                    "gcs_blob_name": gcs_blob_name,
                    "segment_duration": segment_duration_min * 60,
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

    # --- Job Status Polling ---
    if st.session_state.get("split_job_id"):
        st.markdown("---")
        st.subheader("Processing Status")
        poll_job_status(st.session_state.split_job_id)
        st.session_state.split_job_id = None # Clear job so we can start another
