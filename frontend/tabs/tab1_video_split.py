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
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>GCS Direct Upload</title>
      <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #31333F;
            margin: 0;
            padding: 10px;
        }}
        .container {{ display: flex; flex-direction: column; gap: 12px; }}
        #status {{ font-size: 0.9rem; word-wrap: break-word; }}
        button {{
            background-color: #0068c9;
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 600;
        }}
        button:disabled {{
            background-color: #ccc;
            cursor: not-allowed;
        }}
        input[type="file"]::file-selector-button {{
            border-radius: 5px;
            padding: 8px 12px;
            border: 1px solid #ccc;
            background-color: #f0f2f6;
            cursor: pointer;
        }}
      </style>
    </head>
    <body data-api-base-url="{api_base_url}" data-gcs-bucket="{gcs_bucket}" data-workspace="{workspace}">
      <div class="container">
        <input type="file" id="file-input">
        <button id="start-button">Upload to GCS</button>
        <div id="status">Please select a video file and click upload.</div>
      </div>

      <script>
        const fileInput = document.getElementById('file-input');
        const statusDiv = document.getElementById('status');
        const startButton = document.getElementById('start-button');
        const apiBaseUrl = document.body.getAttribute('data-api-base-url');
        const gcsBucket = document.body.getAttribute('data-gcs-bucket');
        const workspace = document.body.getAttribute('data-workspace');

        // Function to communicate from the component to Streamlit
        function setComponentValue(value) {{
            try {{
                console.log('Sending value to Streamlit:', value);
                // Try multiple methods to communicate with Streamlit
                
                // Method 1: Direct postMessage
                if (typeof window.parent !== 'undefined' && window.parent.postMessage) {{
                    window.parent.postMessage({{
                        type: 'streamlit:componentValue',
                        value: value
                    }}, '*');
                }}
                
                // Method 2: Try to use window.parent.streamlitSetComponentValue if available
                if (typeof window.parent.streamlitSetComponentValue === 'function') {{
                    window.parent.streamlitSetComponentValue(value);
                }}
                
                // Method 3: Set a property that Streamlit might check
                if (window.parent && window.parent.document) {{
                    window.parent.document.streamlitComponentValue = value;
                }}
                
            }} catch (e) {{
                console.error('Error sending value to Streamlit:', e);
            }}
        }}

        async function uploadFile(file) {{
            if (!file) {{
                statusDiv.innerText = 'Please select a file first.';
                return;
            }}

            statusDiv.innerText = 'Requesting secure upload link...';
            startButton.disabled = true;

            try {{
                // 1. Get a signed URL from the backend
                const signedUrlResponse = await fetch(`${{apiBaseUrl}}/generate-upload-url/`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        file_name: file.name,
                        content_type: file.type,
                        gcs_bucket: gcsBucket,
                        workspace: workspace
                    }})
                }});

                if (!signedUrlResponse.ok) {{
                    const errorText = await signedUrlResponse.text();
                    throw new Error(`Failed to get signed URL: ${{signedUrlResponse.status}} ${{errorText}}`);
                }}

                const uploadData = await signedUrlResponse.json();
                const {{ upload_url, gcs_blob_name }} = uploadData;

                statusDiv.innerText = `Uploading ${{file.name}} directly to storage...`;

                // 2. Upload the file directly to GCS using the signed URL
                const uploadResponse = await fetch(upload_url, {{
                    method: 'PUT',
                    body: file,
                    headers: {{ 'Content-Type': file.type }}
                }});

                if (!uploadResponse.ok) {{
                    const errorText = await uploadResponse.text();
                    throw new Error(`Upload failed: ${{uploadResponse.status}} ${{errorText}}`);
                }}

                statusDiv.innerHTML = `✅ Upload successful! <br>File: gs://${{gcsBucket}}/${{gcs_blob_name}}. Refresh the page to see your uploaded video`;
                
                // 3. Send the GCS blob name back to the Streamlit app
                setComponentValue(JSON.stringify({{ "gcs_blob_name": gcs_blob_name, "file_name": file.name }}));

            }} catch (error) {{
                statusDiv.innerText = `❌ Error: ${{error.message}}`;
                startButton.disabled = false;
            }}
        }}

        startButton.addEventListener('click', () => {{
            const file = fileInput.files[0];
            uploadFile(file);
        }});

        // Let parent know we're ready
        try {{
            if (typeof window.parent !== 'undefined' && window.parent.postMessage) {{
                window.parent.postMessage({{
                    type: 'streamlit:componentReady',
                    height: 150
                }}, '*');
            }}
        }} catch (e) {{
            console.error('Error sending ready message:', e);
        }}
      </script>
    </body>
    </html>
    """

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
