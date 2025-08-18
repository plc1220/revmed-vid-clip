import streamlit as st
import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Tab Imports ---
from tabs.tab1_video_split import render_tab1
from tabs.tab2_metadata_generation import render_tab2
from tabs.tab3_trailer_generation import render_tab3
from tabs.tab4_refine_clips import render_tab4
from tabs.tab5_video_joining import render_tab5

# --- App Configuration ---
st.set_page_config(layout="wide")
st.title("🎬 Rev-Media Video Assistant")

# --- Global Configuration and Session State Initialization ---
CONFIG_KEYS = {
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    "AI_MODEL_NAME": "gemini-2.5-flash",
    "GCS_BUCKET_NAME": os.getenv("DEFAULT_GCS_BUCKET", "revmedia-vid-clip-bucket"),
    "GCS_PROCESSED_VIDEO_PREFIX": "processed/",
    "GCS_METADATA_PREFIX": "metadata/",
    "GCS_OUTPUT_CLIPS_PREFIX": "clips/",
    "API_BASE_URL": os.getenv("API_BASE_URL", "http://127.0.0.1:8000"),
}

for key, default_value in CONFIG_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# Initialize workspace state
if "workspace" not in st.session_state:
    st.session_state.workspace = None

def render_main_app():
    """Renders the main application tabs."""
    st.header(f"Workspace: `{st.session_state.workspace}`")

    if st.button("Switch Workspace"):
        st.session_state.workspace = None
        st.rerun()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "1: Video Split",
        "2: Metadata Generation",
        "3: Clip Generation",
        "4: Refine Clips by Cast",
        "5: Video Joining"
    ])

    with tab1:
        render_tab1(
            allowed_video_extensions_param=['.mp4', '.mov', '.avi', '.mkv']
        )

    with tab2:
        render_tab2(
            gemini_ready=bool(st.session_state.GEMINI_API_KEY),
            gemini_api_key_global=st.session_state.GEMINI_API_KEY,
            ai_model_name_global=st.session_state.AI_MODEL_NAME,
            allowed_video_extensions_global=['.mp4', '.mov', '.avi', '.mkv'],
        )

    with tab3:
        render_tab3()

    with tab4:
        render_tab4()

    with tab5:
        render_tab5()

# --- Workspace Selection ---
if not st.session_state.workspace:
    st.header("Select or Create a Workspace")

    api_url = st.session_state.API_BASE_URL
    bucket_name = st.session_state.GCS_BUCKET_NAME
    
    try:
        # Fetch existing workspaces
        response = requests.get(f"{api_url}/workspaces/", params={"gcs_bucket": bucket_name})
        response.raise_for_status()
        workspaces = response.json().get("workspaces", [])
        
        # Workspace Selector
        selected_workspace = st.selectbox("Select a workspace:", options=workspaces)
        
        if st.button("Enter Workspace"):
            if selected_workspace:
                st.session_state.workspace = selected_workspace
                st.rerun()
            else:
                st.warning("Please select a workspace.")

    except requests.exceptions.RequestException as e:
        st.error(f"Could not connect to the backend API to fetch workspaces. Please ensure the API is running. Error: {e}")
        st.stop()

    st.markdown("---")
    
    # Workspace Creator
    st.subheader("Or, Create a New Workspace")
    new_workspace_name = st.text_input("New workspace name:")
    
    if st.button("Create and Enter Workspace"):
        if new_workspace_name:
            try:
                response = requests.post(
                    f"{api_url}/workspaces/",
                    params={"workspace_name": new_workspace_name, "gcs_bucket": bucket_name}
                )
                response.raise_for_status()
                st.session_state.workspace = new_workspace_name
                st.success(f"Workspace '{new_workspace_name}' created successfully!")
                st.rerun()
            except requests.exceptions.RequestException as e:
                st.error(f"Failed to create workspace. Error: {e.response.text if e.response else e}")
        else:
            st.warning("Please enter a name for the new workspace.")
else:
    # Render the main application
    render_main_app()