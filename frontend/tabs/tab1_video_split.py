import streamlit as st
import os
import requests
import time
import streamlit.components.v1 as components
import json

def large_file_uploader(api_base_url: str, gcs_bucket: str, workspace: str, allowed_extensions: list):
    """A custom Streamlit component to handle large file uploads directly to GCS."""
    
    # Generate a unique key for the file input element to allow re-uploading the same file
    component_key = f"large_file_uploader_{int(time.time())}"

    js_code = f"""
    <script>
    const fileInput = document.getElementById('fileUploader');
    const uploadButton = document.getElementById('uploadButton');
    const statusDiv = document.getElementById('status');
    const progressBar = document.getElementById('progressBar');
    const progressContainer = document.getElementById('progressContainer');
    const progressText = document.getElementById('progressText');

    uploadButton.addEventListener('click', async () => {{
        const file = fileInput.files[0];
        if (!file) {{
            statusDiv.innerHTML = 'Please select a file first.';
            return;
        }}

        statusDiv.innerHTML = 'Initializing upload...';
        progressContainer.style.display = 'block';
        progressBar.style.width = '0%';
        progressText.textContent = '0%';

        try {{
            // 1. Get signed URL from our backend
            const backendUrl = '{api_base_url}'.replace('backend:8080', 'localhost:8000');
            const payload = {{
                file_name: file.name,
                content_type: file.type || 'application/octet-stream',
                workspace: '{workspace}',
                gcs_bucket: '{gcs_bucket}'
            }};

            const configResponse = await fetch(`${{backendUrl}}/gcs/generate-upload-url`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }});

            if (!configResponse.ok) {{
                const errorData = await configResponse.json();
                throw new Error(`Could not get signed URL from backend: ${{errorData.detail || configResponse.statusText}}`);
            }}
            const {{ signed_url, gcs_blob_name }} = await configResponse.json();

            // 2. Upload the file directly to GCS using the signed URL
            statusDiv.innerHTML = `Uploading ${{file.name}}...`;
            
            const xhr = new XMLHttpRequest();
            xhr.open('PUT', signed_url, true);
            xhr.setRequestHeader('Content-Type', payload.content_type);

            xhr.upload.onprogress = (event) => {{
                if (event.lengthComputable) {{
                    const percentComplete = Math.round((event.loaded / event.total) * 100);
                    progressBar.style.width = percentComplete + '%';
                    progressText.textContent = percentComplete + '%';
                }}
            }};

            xhr.onload = () => {{
                if (xhr.status === 200) {{
                    statusDiv.innerHTML = `✅ File successfully uploaded to gs://{gcs_bucket}/${{gcs_blob_name}}`;
                    window.parent.postMessage({{
                        isStale: true,
                        type: "streamlit:setComponentValue",
                        value: {{
                            "gcs_blob_name": gcs_blob_name,
                            "file_name": file.name,
                            "file_size": file.size,
                            "file_type": file.type
                        }}
                    }}, "*");
                }} else {{
                    statusDiv.innerHTML = `❌ Upload failed. Status: ${{xhr.status}} - ${{xhr.statusText}}`;
                    window.parent.postMessage({{ isStale: true, type: "streamlit:setComponentValue", value: null }}, "*");
                }}
            }};

            xhr.onerror = () => {{
                statusDiv.innerHTML = '❌ An error occurred during the upload. Please check the browser console.';
                window.parent.postMessage({{ isStale: true, type: "streamlit:setComponentValue", value: null }}, "*");
            }};

            xhr.send(file);

        }} catch (error) {{
            statusDiv.innerHTML = `❌ An error occurred: ${{error.message}}`;
            window.parent.postMessage({{ isStale: true, type: "streamlit:setComponentValue", value: null }}, "*");
        }}
    }});
    </script>
    """

    html_template = f"""
    <div style="font-family: sans-serif; padding: 1rem; border: 1px solid #ccc; border-radius: 5px;">
        <h4>Upload a large video file</h4>
        <input type="file" id="fileUploader" accept="{','.join(allowed_extensions)}">
        <button id="uploadButton" style="margin-top: 10px; padding: 8px 12px;">Upload to GCS</button>
        <div id="status" style="margin-top: 10px;"></div>
        <div id="progressContainer" style="width: 100%; background-color: #f3f3f3; border-radius: 5px; margin-top: 10px; display: none;">
            <div id="progressBar" style="width: 0%; height: 20px; background-color: #4CAF50; border-radius: 5px;"></div>
        </div>
        <div id="progressText" style="margin-top: 5px; text-align: center; font-weight: bold;">0%</div>
        </div>
    </div>
    {js_code}
    """
    
    return components.html(html_template, height=250)

def render_tab1(allowed_video_extensions_param: list):
    st.header("Step 1: Video Split")

    st.info(
        "This tool uses a direct-to-storage upload method for robust, large video processing. "
        "Upload your video, and the system will handle the splitting in the background."
    )

    # Initialize session state variables for this tab
    if "split_job_id" not in st.session_state:
        st.session_state.split_job_id = None
    if "split_job_status" not in st.session_state:
        st.session_state.split_job_status = None
    if "split_job_details" not in st.session_state:
        st.session_state.split_job_details = ""
    if "uploaded_gcs_blob" not in st.session_state:
        st.session_state.uploaded_gcs_blob = None

    gcs_bucket = st.session_state.get("GCS_BUCKET_NAME", "revmedia-vid-clip-bucket")
    
    # --- File Uploader ---
    with st.expander("Upload a new video", expanded=True):
        large_file_uploader(
            api_base_url=st.session_state.API_BASE_URL,
            gcs_bucket=gcs_bucket,
            workspace=st.session_state.workspace,
            allowed_extensions=[ext.lstrip('.') for ext in allowed_video_extensions_param]
        )

    st.markdown("---")
    st.subheader("Select a video to split")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("Choose a video from the list below. Click 'Refresh' to see newly uploaded files.")
    with col2:
        if st.button("🔄 Refresh List"):
            st.cache_data.clear() # Clear cache to force a re-fetch
            st.rerun()

    # --- Video Selection ---
    try:
        list_url = f"{st.session_state.API_BASE_URL}/gcs/list"
        params = {
            "gcs_bucket": gcs_bucket,
            "prefix": f"{st.session_state.workspace}/uploads/"
        }
        response = requests.get(list_url, params=params)
        response.raise_for_status()
        video_files = response.json().get("files", [])

        if not video_files:
            st.warning("No videos found in the workspace uploads directory. Please upload a file first.")
            return

        # Initialize or update selection state
        if 'video_selection_split' not in st.session_state:
            st.session_state.video_selection_split = {}

        # Update state for current list of videos, preserving existing selections
        current_selection = st.session_state.video_selection_split.copy()
        st.session_state.video_selection_split = {uri: current_selection.get(uri, False) for uri in video_files}

        # --- Selection Controls ---
        col1, col2, _ = st.columns([0.15, 0.15, 0.7])
        with col1:
            if st.button("Select All", key="select_all_videos_split"):
                for uri in video_files:
                    st.session_state.video_selection_split[uri] = True
                st.rerun()
        with col2:
            if st.button("Deselect All", key="deselect_all_videos_split"):
                for uri in video_files:
                    st.session_state.video_selection_split[uri] = False
                st.rerun()

        # --- Video List with Checkboxes ---
        st.write("Select a video file to split:")
        for uri in video_files:
            is_selected = st.checkbox(
                os.path.basename(uri),
                value=st.session_state.video_selection_split.get(uri, False),
                key=f"cb_split_{uri}"
            )
            st.session_state.video_selection_split[uri] = is_selected
        
        selected_videos = [uri for uri, selected in st.session_state.video_selection_split.items() if selected]

        if len(selected_videos) > 1:
            st.warning("Please select only one video to split.")
        elif len(selected_videos) == 1:
            full_blob_name = selected_videos[0]
            selected_blob_name = os.path.basename(full_blob_name)
            
            st.success(f"Ready to process: `{selected_blob_name}`")
            st.write(f"GCS Path: `gs://{gcs_bucket}/{full_blob_name}`")

            segment_duration_min = st.number_input(
                "Max duration per chunk (minutes):",
                min_value=1, value=5, step=1, key="segment_duration_input"
            )

            if st.button("🚀 Start Splitting", key="split_video_button"):
                st.session_state.split_job_id = None
                st.session_state.split_job_status = None
                st.session_state.split_job_details = ""

                try:
                    with st.spinner("Starting video splitting job..."):
                        split_url = f"{st.session_state.API_BASE_URL}/split-video/"
                        payload = {
                            "workspace": st.session_state.workspace,
                            "gcs_bucket": gcs_bucket,
                            "gcs_blob_name": full_blob_name,
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
            st.info("Please select a video from the list to enable splitting options.")

    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch video list from the backend: {e}")

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