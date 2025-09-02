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
from tabs.tab6_final_result import show as render_tab6
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

st.title(t("app_title"))

# --- Global Configuration and Session State Initialization ---
load_config()

# Initialize workspace state
if "workspace" not in st.session_state:
    st.session_state.workspace = None


def render_main_app():
    """Renders the main application tabs."""
    col_1, col_2, col_3 = st.columns([4, 1, 1])
    col_1.header(t("workspace_header").format(workspace=st.session_state.workspace))

    if col_2.button(t("switch_workspace_button"), use_container_width=True, icon=":material/arrow_back:"):
        st.session_state.workspace = None
        st.rerun()

    if col_3.button(t("refresh_button"), use_container_width=True, icon=":material/refresh:"):
        st.rerun()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            t("tab1_title"),
            t("tab2_title"),
            t("tab3_title"),
            t("tab4_title"),
            t("tab5_title"),
            t("tab6_title"),
        ]
    )

    with tab1:
        render_tab1(allowed_video_extensions_param=[".mp4", ".mov", ".avi", ".mkv"])

    with tab2:
        render_tab2(
            ai_model_name_global=st.session_state.AI_MODEL_NAME,
            allowed_video_extensions_global=[".mp4", ".mov", ".avi", ".mkv"],
        )

    with tab3:
        render_tab3()

    with tab4:
        render_tab4()

    with tab5:
        render_tab5()

    with tab6:
        render_tab6()


def render_workspace_management():
    """Renders the workspace selection and creation UI."""
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
