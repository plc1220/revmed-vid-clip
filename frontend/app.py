import streamlit as st
import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from config import load_config
from localization import LANGUAGES, load_translation, get_translator

# --- App Configuration ---
st.set_page_config(layout="wide")
# --- Language Selection ---
selected_language = st.sidebar.selectbox(
    "Language",
    options=list(LANGUAGES.keys()),
    index=0,  # Default to English
)

# Load translations
st.session_state.selected_language = selected_language
st.session_state.translations = load_translation(selected_language)
t = get_translator()

# --- Global Configuration and Session State Initialization ---
load_config()

# Initialize workspace state
if "workspace" not in st.session_state:
    st.session_state.workspace = None


def render_main_app():
    # col_1, col_2, col_3 = st.columns([3, 1, 1])
    st.header(st.session_state.workspace)

    if st.sidebar.button(t("switch_workspace_button"), use_container_width=True, icon=":material/arrow_back:"):
        st.session_state.workspace = None
        st.rerun()

    if st.sidebar.button(t("refresh_button"), use_container_width=True, icon=":material/refresh:"):
        st.rerun()

    page_1 = st.Page("pages/1_video_split.py", title="Video Split", icon=":material/split_scene:")
    page_2 = st.Page("pages/2_metadata_generation.py", title="Metadata Generation", icon=":material/movie_info:")
    page_3 = st.Page("pages/3_clips_generation.py", title="Clips Generation", icon=":material/movie:")
    page_4 = st.Page("pages/4_refine_clips.py", title="Refine Clips by Cast", icon=":material/face:")
    page_5 = st.Page("pages/5_video_joining.py", title="Video Joining", icon=":material/video_library:")
    page_6 = st.Page("pages/6_final_result.py", title="Final Result", icon=":material/editor_choice:")

    pg = st.navigation([page_1, page_2, page_3, page_4, page_5, page_6])

    pg.run()


def render_workspace_management():
    """Renders the workspace selection and creation UI."""
    st.title(t("app_title"))
    st.header(t("workspace_management_header"))

    api_url = st.session_state.API_BASE_URL
    bucket_name = st.session_state.GCS_BUCKET_NAME

    try:
        # Fetch existing workspaces
        response = requests.get(f"{api_url}/workspaces/", params={"gcs_bucket": bucket_name})
        response.raise_for_status()
        workspaces = response.json().get("workspaces", [])

        # Workspace Selector
        selected_workspace = st.selectbox(t("select_workspace_label"), options=workspaces)

        if st.button(t("enter_workspace_button")):
            if selected_workspace:
                st.session_state.workspace = selected_workspace
                st.rerun()
            else:
                st.warning(t("select_workspace_warning"))

    except requests.exceptions.RequestException as e:
        st.error(
            t("backend_connection_error").format(e=e)
        )
        st.stop()

    st.markdown("---")

    # Workspace Creator
    st.subheader(t("create_workspace_subheader"))
    new_workspace_name = st.text_input(t("new_workspace_label"))

    if st.button(t("create_enter_workspace_button")):
        if new_workspace_name:
            try:
                response = requests.post(
                    f"{api_url}/workspaces/", params={"workspace_name": new_workspace_name, "gcs_bucket": bucket_name}
                )
                response.raise_for_status()
                st.session_state.workspace = new_workspace_name
                st.success(t("workspace_creation_success").format(workspace_name=new_workspace_name))
                st.rerun()
            except requests.exceptions.RequestException as e:
                st.error(t("workspace_creation_error").format(e=e.response.text if e.response else e))
        else:
            st.warning(t("enter_workspace_name_warning"))

# --- Main App Logic ---
if not st.session_state.workspace:
    render_workspace_management()
else:
    render_main_app()
