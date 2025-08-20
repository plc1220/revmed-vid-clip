import os
import streamlit as st

def get_config():
    """
    Returns a dictionary of configuration values from environment variables.
    """
    return {
        "AI_MODEL_NAME": "gemini-2.5-flash",
        "GCS_BUCKET_NAME": os.getenv("DEFAULT_GCS_BUCKET", "lc-ccob-test"),
        "GCS_PROCESSED_VIDEO_PREFIX": "processed/",
        "GCS_METADATA_PREFIX": "metadata/",
        "GCS_OUTPUT_CLIPS_PREFIX": "clips/",
        "API_BASE_URL": os.getenv("API_BASE_URL", "http://backend:8080"),
    }

def load_config():
    """
    Loads the configuration into the Streamlit session state.
    """
    config = get_config()
    for key, default_value in config.items():
        if key not in st.session_state:
            st.session_state[key] = default_value