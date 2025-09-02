import streamlit as st
import json
import os

LANGUAGES = {
    "English": "en",
    "Bahasa Malaysia": "ms",
    "中文 (Simplified)": "zh_CN",
}

def load_translation(language):
    """Loads the translation file for the selected language."""
    lang_code = LANGUAGES.get(language, "en")
    # The WORKDIR in the Dockerfile is /app, so the path should be relative to that.
    file_path = os.path.join("languages", f"{lang_code}.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"Translation file not found for {language} ({lang_code}.json). Falling back to English.")
        # Fallback to English if the language file is missing
        file_path = os.path.join("languages", "en.json")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

def get_translator():
    """
    Returns a function that translates a given key into the selected language.
    """
    if "translations" not in st.session_state:
        st.session_state.translations = load_translation("English") # Default to English

    def translate(key):
        return st.session_state.translations.get(key, key)

    return translate