import streamlit as st
import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Tab Imports ---
from tabs.tab1_video_split import render_tab1
from tabs.tab2_metadata_generation import render_tab2
from tabs.tab3_trailer_generation import render_tab3
from tabs.tab4_video_joining import render_tab4
from tabs.tab5_generate_clips_ai import render_tab5

# --- App Configuration ---
st.set_page_config(layout="wide")
st.title("🎬 Rev-Media Video Assistant")

# --- Global Configuration and Session State Initialization ---
CONFIG_KEYS = {
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    "AI_MODEL_NAME": "gemini-2.5-flash",
    "GCS_BUCKET_NAME": os.getenv("DEFAULT_GCS_BUCKET", "lc-ccob-test"),
    "GCS_PROCESSED_VIDEO_PREFIX": "processed/",
    "GCS_METADATA_PREFIX": "metadata/",
    "GCS_OUTPUT_CLIPS_PREFIX": "clips/",
    "API_BASE_URL": "http://127.0.0.1:8000",
}

for key, default_value in CONFIG_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# # --- Sidebar for Global Settings ---
# st.sidebar.header("⚙️ Global Configurations")

# st.session_state.GCS_BUCKET_NAME = st.sidebar.text_input(
#     "GCS Bucket Name:",
#     value=st.session_state.GCS_BUCKET_NAME,
#     key="cfg_gcs_bucket_name"
# )
# st.session_state.GEMINI_API_KEY = st.sidebar.text_input(
#     "Gemini API Key:",
#     value=st.session_state.GEMINI_API_KEY,
#     type="password",
#     key="cfg_gemini_api_key"
# )
# st.session_state.AI_MODEL_NAME = st.sidebar.text_input(
#     "AI Model Name:",
#     value=st.session_state.AI_MODEL_NAME,
#     key="cfg_ai_model_name"
# )
# st.session_state.API_BASE_URL = st.sidebar.text_input(
#     "Backend API URL:",
#     value=st.session_state.API_BASE_URL,
#     key="cfg_api_base_url"
# )

# st.sidebar.subheader("GCS Folder Prefixes")
# st.session_state.GCS_PROCESSED_VIDEO_PREFIX = st.sidebar.text_input(
#     "Processed Videos Prefix:",
#     value=st.session_state.GCS_PROCESSED_VIDEO_PREFIX,
#     key="cfg_gcs_processed_video_prefix"
# )
# st.session_state.GCS_METADATA_PREFIX = st.sidebar.text_input(
#     "Metadata Prefix:",
#     value=st.session_state.GCS_METADATA_PREFIX,
#     key="cfg_gcs_metadata_prefix"
# )
# st.session_state.GCS_OUTPUT_CLIPS_PREFIX = st.sidebar.text_input(
#     "Output Clips Prefix:",
#     value=st.session_state.GCS_OUTPUT_CLIPS_PREFIX,
#     key="cfg_gcs_output_clips_prefix"
# )

# --- Health Check for Backend API ---
# api_ready = False
# try:
#     response = requests.get(f"{st.session_state.API_BASE_URL}/")
#     if response.status_code == 200:
#         api_ready = True
#         st.sidebar.success("✅ Backend API is connected.")
#     else:
#         st.sidebar.error(f"❌ Backend API returned status {response.status_code}.")
# except requests.exceptions.ConnectionError:
#     st.sidebar.error("❌ Backend API is not reachable.")

# --- Main Application Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1: Video Split",
    "2: Metadata Generation",
    "3: Clip Generation",
    "4: Video Joining",
    "5: AI Clip Generation"
])

with tab1:
    render_tab1(
        temp_split_output_dir_param="./temp_split_output", # This is now managed by the API
        allowed_video_extensions_param=['.mp4', '.mov', '.avi', '.mkv']
    )

with tab2:
    render_tab2(
        gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME,
        gcs_prefix_param=st.session_state.GCS_PROCESSED_VIDEO_PREFIX,
        gemini_ready=bool(st.session_state.GEMINI_API_KEY),
        metadata_output_dir_global="./temp_metadata_output", # Managed by API
        gemini_api_key_global=st.session_state.GEMINI_API_KEY,
        ai_model_name_global=st.session_state.AI_MODEL_NAME,
        concurrent_api_calls_limit=5, # Managed by API
        allowed_video_extensions_global=['.mp4', '.mov', '.avi', '.mkv'],
        gcs_metadata_bucket_name=st.session_state.GCS_BUCKET_NAME,
        gcs_output_metadata_prefix_param=st.session_state.GCS_METADATA_PREFIX
    )

with tab3:
    render_tab3(gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME)

with tab4:
    render_tab4(gcs_bucket_name=st.session_state.GCS_BUCKET_NAME)

with tab5:
    render_tab5(
        gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME,
        gemini_api_key_param=st.session_state.GEMINI_API_KEY,
        ai_model_name_param=st.session_state.AI_MODEL_NAME,
        temp_clips_output_dir_param="./temp_clip_output", # Managed by API
        temp_ai_clips_individual_output_dir_param="./temp_ai_clip", # Managed by API
        temp_ai_video_joined_output_dir_param="./temp_ai_joined_video", # Managed by API
        gcs_processed_video_prefix_param=st.session_state.GCS_PROCESSED_VIDEO_PREFIX,
        gcs_metadata_prefix_param=st.session_state.GCS_METADATA_PREFIX,
        gcs_output_clips_prefix_param=st.session_state.GCS_OUTPUT_CLIPS_PREFIX,
        gemini_ready_param=bool(st.session_state.GEMINI_API_KEY)
    )