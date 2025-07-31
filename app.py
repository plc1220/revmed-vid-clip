import streamlit as st
from google.cloud import storage
import google.generativeai as genai
import os # Keep for os.getenv, os.path, os.makedirs
import sys
# Attempt to help Pylance resolve imports by adding site-packages to sys.path
# This path was identified from the pip install output for moviepy.
# Ensure this path matches your actual moviepy installation location.
_site_packages_path = '/Users/weichunglow/miniforge3/lib/python3.9/site-packages'
if _site_packages_path not in sys.path:
    sys.path.append(_site_packages_path)
# streamlit.runtime.scriptrunner is not directly used here anymore, but might be by imported tabs
# from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx

# --- Tab Imports ---
from tabs.tab1_video_split import render_tab1
from tabs.tab2_metadata_generation import render_tab2
from tabs.tab3_trailer_generation import render_tab3
from tabs.tab4_video_joining import render_tab4
from tabs.tab5_generate_clips_ai import render_tab5

# google.cloud.storage and google.generativeai are used by helper functions below
from google.cloud import storage
import google.generativeai as genai


# --- Version Check (Good for debugging) ---
# --- ABSOLUTELY CRITICAL: Initialize Session State AT THE VERY TOP ---
# Config keys for session state
CONFIG_KEYS = {
    "GEMINI_API_KEY": "AIzaSyBkuO_FfMRh1mvcy6XGKTbxPsR9mqCracg", # Default from get_model.py
    "AI_MODEL_NAME": "gemini-2.5-pro",
    "GCS_BUCKET_NAME": os.getenv("DEFAULT_GCS_BUCKET", "weichung-rev"),
    "TEMP_SPLIT_OUTPUT_DIR": "./temp_split_output",
    "METADATA_OUTPUT_DIR": "./temp_metadata_output",
    "TEMP_CLIPS_OUTPUT_DIR_TAB5": "./temp_clip_output",
    "TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5": "./temp_ai_clip",
    "TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5": "./temp_ai_joined_video",
    "GCS_PROCESSED_VIDEO_PREFIX": "processed/",
    "GCS_METADATA_PREFIX_TAB5": "metadata/",
    "GCS_OUTPUT_CLIPS_PREFIX_TAB5": "clips/"
}

# Initialize config from session state or defaults
for key, default_value in CONFIG_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# These session states are for Tab 1 (Video Splitting)
if "selected_video_for_split" not in st.session_state:
    st.session_state.selected_video_for_split = None
if "is_splitting" not in st.session_state:
    st.session_state.is_splitting = False
if "split_progress" not in st.session_state:
    st.session_state.split_progress = 0
if "split_progress_bar_placeholder" not in st.session_state:
    st.session_state.split_progress_bar_placeholder = None # Tab 1 uses this
if "split_error_message" not in st.session_state:
    st.session_state.split_error_message = None
if "split_success_message" not in st.session_state:
    st.session_state.split_success_message = None
if "splitting_thread" not in st.session_state:
    st.session_state.splitting_thread = None
if "stop_splitting_requested" not in st.session_state:
    st.session_state.stop_splitting_requested = False

# These session states are for Tab 2 (Metadata Generation)
# They are initialized within render_tab2 now, but if any were truly global, they'd be here.
# For example, if a global "Gemini is busy" flag was needed across tabs.
# if "is_batch_processing" not in st.session_state: ... (moved to tab2)

# These session states are for Tab 3 (Trailer Generation)
if "selected_gcs_metadata_file_tab3" not in st.session_state:
    st.session_state.selected_gcs_metadata_file_tab3 = None
if "selected_gcs_metadata_content_tab3" not in st.session_state:
    st.session_state.selected_gcs_metadata_content_tab3 = ""
if "trailer_details_input_content_tab3" not in st.session_state:
    st.session_state.trailer_details_input_content_tab3 = """metadata_file_1.txt
metadata_file_2.txt
# Or, manual segment definitions:
# video_part_A.mp4, theme:action, duration:10s
# video_part_B.mp4, theme:dialogue, duration:5s"""
if "output_clip_filename_style_tab3" not in st.session_state: # For Tab 3's output filename
    st.session_state.output_clip_filename_style_tab3 = "default_clip_X.mp4"

# These session states are for Tab 5 (Generate Clips with AI)
if "selected_gcs_metadata_file_tab5" not in st.session_state:
    st.session_state.selected_gcs_metadata_file_tab5 = None
if "selected_gcs_metadata_content_tab5" not in st.session_state:
    st.session_state.selected_gcs_metadata_content_tab5 = ""
if "trailer_details_input_content_tab5" not in st.session_state:
    st.session_state.trailer_details_input_content_tab5 = """metadata_file_1.txt
metadata_file_2.txt
# Or, manual segment definitions:
# video_part_A.mp4, theme:action, duration:10s
# video_part_B.mp4, theme:dialogue, duration:5s"""
if "output_clip_filename_style_tab5" not in st.session_state: # For Tab 5's output filename
    st.session_state.output_clip_filename_style_tab5 = "ai_clip_X.mp4" # Different default for AI tab
if "generated_clips_paths_tab5" not in st.session_state:
    st.session_state.generated_clips_paths_tab5 = []
if "raw_gcs_metadata_content_tab5" not in st.session_state: # For Tab 5, raw content from all GCS files
    st.session_state.raw_gcs_metadata_content_tab5 = ""

# Generic Gemini states (if used by other parts of app, or a future single-call Gemini feature)
if "gemini_response" not in st.session_state:
    st.session_state.gemini_response = None
if "error_message" not in st.session_state: # General error for a single Gemini call
    st.session_state.error_message = None
# ... other generic states if any ...


# --- Configuration (Global) ---
# GCS_METADATA_OUTPUT_BUCKET_NAME = "weichung-rev" # Bucket for storing generated metadata - now part of general bucket config or could be separate if needed
# DEFAULT_BUCKET_NAME = "weichung-rev" # Now handled by session state
# PROCESSED_GCS_FOLDER_NAME = "processed/" # Now handled by session state
# METADATA_OUTPUT_DIR = "./temp_metadata_output" # Now handled by session state
# TEMP_SPLIT_OUTPUT_DIR = "./temp_split_output" # Now handled by session state
ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv'] # Used by Tab 1 and GCS listing
CONCURRENT_API_CALLS_LIMIT = 5 # Default limit for concurrent Gemini API calls

# Ensure directories exist based on session state values
# These will be updated by sidebar inputs later
os.makedirs(st.session_state.METADATA_OUTPUT_DIR, exist_ok=True)
os.makedirs(st.session_state.TEMP_SPLIT_OUTPUT_DIR, exist_ok=True)
os.makedirs(st.session_state.TEMP_CLIPS_OUTPUT_DIR_TAB5, exist_ok=True)
os.makedirs(st.session_state.TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5, exist_ok=True)
os.makedirs(st.session_state.TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5, exist_ok=True)


prompt_text = """
You are a professional film and drama editor AI, equipped with multimodal understanding (visuals, dialogue, sound, and inferred emotion). Your task is to meticulously analyze the provided video content of an **appmaximum 10-minute video clip from a drama series.** Your goal is to identify multiple key moments suitable for constructing a dynamic and engaging 2-minute trailer from **this specific clip.**

For each potential trailer moment you identify **within this video clip**, extract and structure the following metadata. Be precise and insightful.

**Input to Analyze:**
*   **Primary:** The video content of the **provided max 10-minute drama clip. Some clip can be shorter. Make sure you only capture the scene within the length of that video**
*   **Supplementary (if provided):** A transcript or scene-by-scene description. Your analysis should prioritize what is seen and heard in the video, using supplementary text to clarify or confirm dialogue and scene context if available.

**Prioritize Moments That (within the ~10-minute clip):**
*   Introduce key characters effectively.
*   Establish the central conflict or mystery.
(Rest of the prioritization list)

**Output Requirements:**
Provide your response as a single, valid JSON array. Each element in the array should be a JSON object representing one potential trailer clip. Each object must contain the following fields:

1.  **`source_filename`**:
    *   Description: The filename of the **specific ~10-minute video clip** being analyzed.
    *   Example: "cinta-buat-dara-S1E1_part1.mp4"
2.  **`timestamp_start_end`**:
    *   Description: Precise in and out points for the clip (HH:MM:SS - HH:MM:SS) **relative to the start of the provided video file.** Aim for clips 2-15 seconds long. **All timestamps (both start and end) MUST be within the actual duration of the input video clip `source_filename`. Do not generate timestamps exceeding the video's length.**
    *   Example: "00:02:15 - 00:02:30" (This would be valid for a 10-minute clip, but "00:12:00 - 00:12:10" would be invalid).
3.  **`editor_note_clip_rationale`**:
    *   Description: Your rationale for selecting this clip. Why is it trailer-worthy? (Max 30 words)
    *   Example: "The mother threatens Dara's prized possession, creating a cliffhanger for her rebellious streak and showcasing immediate conflict."
4.  **`brief_scene_description`**:
    *   Description: Concisely summarize the core action, setting, and characters. Focus on visual/narrative significance. (Max 25 words)
    *   Example: "Character A confronts Character B in a dimly lit alley during a storm. Close up on A's determined, angry face."
5.  **`key_dialogue_snippet`**:
    *   Description: Most potent, intriguing, or revealing line(s) of dialogue (verbatim, max 2 lines). If none, state "None" or "Action/Visual Only."
    *   Example: "Mama: \"Mama tahu macam mana nak ubat Dara!\" Dara: (Screaming) \"No! Mama! Mama, Dara minta maaf Mama!\""
6.  **`dominant_emotional_tone_impact`**:
    *   Description: Primary feeling(s) or impact evoked. (Max 5 keywords, comma-separated)
    *   Example: "Tense, Confrontational, Betrayal, Shock, Anger"
7.  **`key_visual_elements_cinematography`**:
    *   Description: Striking visuals, camera work, lighting, significant props/symbols. (Max 5 keywords/phrases, comma-separated)
    *   Example: "Dramatic low-angle, Rain-streaked, Fast cuts, Close-up on eyes, Flickering neon sign"
8.  **`characters_in_focus_objective_emotion`**:
    *   Description: Who is central? Their objective or strong emotion? (Max 15 words)
    *   Example: "Sarah (desperate) trying to escape."
9.  **`plot_relevance_significance`**:
    *   Description: Why is this moment important for the narrative or trailer? (Max 20 words)
    *   Example: "Introduces main antagonist and the core personal conflict."
10. **`trailer_potential_category`**:
    *   Description: How could this clip be used? (Choose one or two from list, comma-separated)
    *   Options: Hook/Opening, Character Introduction, Inciting Incident, Conflict Build-up, Rising Action, Tension/Suspense Peak, Emotional Beat, Action Sequence Highlight, Twist/Reveal Tease, Climax Tease, Resolution Glimpse, Cliffhanger/Question, Thematic Montage Element
    *   Example: "Cliffhanger/Question, Tension/Suspense Peak"
11. **`pacing_suggestion_for_clip`**:
    *   Description: How should this clip feel in a trailer sequence? (Choose one from list)
    *   Options: Rapid Cut, Medium Pace, Slow Burn/Held Shot, Builds Intensity, Sudden Impact
    *   Example: "Builds Intensity"
12. **`music_sound_cue_idea`**:
    *   Description: Optional. Sound to amplify the moment. (Max 10 words)
    *   Example: "Sudden silence then impact sound."

    **Crucial JSON Formatting Rules:**
*   The generated JSON must be strictly valid according to standard JSON syntax (RFC 8259).
*   **Specifically, ensure there are NO TRAILING COMMAS after the last element in an array or the last key-value pair in an object.** For example, `["item1", "item2"]` is correct, but `["item1", "item2",]` is incorrect. Similarly, `{{"key1": "value1", "key2": "value2"}}` is correct, but `{{"key1": "value1", "key2": "value2",}}` is incorrect.
*   All strings within the JSON (keys and values) must be enclosed in double quotes and properly escaped if they contain special characters (e.g., double quotes within a string should be escaped as `\"`).
*   If a category (diagnoses, observations, etc.) has no items, use an empty array `[]` for that category's list. For the summary, if no summary can be generated, provide an empty string `""` or a "None available." string.
*   After generating the JSON, please perform a quick check to ensure it is valid JSON syntax according to the rules mentioned above.
*   A common error is forgetting a comma or a colon between elements. For instance, 
    `{{"description\": \"A\" \"codes\": [\"C\"]` is WRONG because it's missing a comma after `\"A\"`. It should be `{{\"description\": \"A\", \"codes\": [\"C\"]}}`.
*   Please meticulously check for missing commas before outputting the JSON.
*   Is there an unclosed string (") on a previous line that's making the parser confused?
*   Is all property enclosed with double quote (")

**Example JSON Object for a single clip (Remember, you will return an ARRAY of these):**
{
  "source_filename": "cinta-buat-dara-S1E1_part1.mp4",
  "timestamp_start_end": "00:09:31 - 00:09:45",
  "editor_note_clip_rationale": "The mother threatens Dara's prized possession, creating a cliffhanger for her rebellious streak.",
  "brief_scene_description": "Mama grabs Dara's skateboard, threatening to break it, while Dara watches in horror, screaming.",
  "key_dialogue_snippet": "Mama: \"Mama tahu macam mana nak ubat Dara!\" Dara: (Screaming as Mama approaches with the skateboard to smash it) \"No! Mama! Mama! No! Mama! Mama, Dara minta maaf Mama! Dara minta maaf!\"",
  "dominant_emotional_tone_impact": "Threatening, Intense, Desperate, Shock, Fear",
  "key_visual_elements_cinematography": "Close up on Mama's determined/angry face, Skateboard as a weapon, Dara's horrified reaction, Slow-motion tease of smashing",
  "characters_in_focus_objective_emotion": "Mama (threatening punishment). Dara (terrified of losing her skateboard, begging).",
  "plot_relevance_significance": "High-stakes personal conflict, threat to Dara's valued possession, potential cliffhanger.",
  "trailer_potential_category": "Cliffhanger/Question, Tension/Suspense Peak, Emotional Beat",
  "pacing_suggestion_for_clip": "Builds Intensity rapidly, possibly with slow-motion on the \"smash\" tease.",
  "music_sound_cue_idea": "Intense sound design, cracking/smashing sound effect (teased), Dara's scream."
}
"""

# --- Helper Functions (Still needed globally for Tab 2) ---

def ensure_gcs_folder_exists(bucket_name, folder_name):
    """Ensures a GCS 'folder' exists by creating a .placeholder file if it's empty."""
    if not folder_name.endswith('/'):
        folder_name += '/'
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=folder_name, max_results=1))
        if not blobs:
            placeholder_blob_name = f"{folder_name}.gcs_folder_placeholder"
            blob = bucket.blob(placeholder_blob_name)
            blob.upload_from_string("", content_type="text/plain")
            print(f"Created placeholder for GCS folder: gs://{bucket_name}/{folder_name}")
            return True, None
        return True, None
    except Exception as e:
        error_msg = f"Error ensuring GCS folder gs://{bucket_name}/{folder_name} exists: {e}"
        print(error_msg)
        return False, error_msg

@st.cache_data(ttl=600)
def list_gcs_videos(bucket_name, prefix=""):
    videos = []
    error_message = None
    if prefix and not prefix.endswith('/'):
        prefix += '/'

    if not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
        print(f"WARNING: GOOGLE_APPLICATION_CREDENTIALS not set. GCS listing for gs://{bucket_name}/{prefix} will use dummy data.")
        if prefix:
            return [f"{prefix}SampleVideo1.mp4", f"{prefix}SampleVideo2.mp4"], None
        else:
            return ["SampleVideo1.mp4", "SampleVideo2.mp4"], None
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            return [], f"Bucket '{bucket_name}' does not exist or you don't have access."
        if prefix:
            folder_exists, folder_error = ensure_gcs_folder_exists(bucket_name, prefix)
            if not folder_exists:
                return [], folder_error
        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            if blob.name == f"{prefix}.gcs_folder_placeholder":
                continue
            if any(blob.name.lower().endswith(ext) for ext in ALLOWED_VIDEO_EXTENSIONS):
                videos.append(blob.name)
        display_location = f"folder '{prefix}' in bucket '{bucket_name}'" if prefix else f"bucket '{bucket_name}'"
        if not videos:
            return [], f"No video files ({', '.join(ALLOWED_VIDEO_EXTENSIONS)}) found in {display_location}."
    except Exception as e:
        error_message = f"Error listing GCS files from gs://{bucket_name}/{prefix}: {e}"
        print(f"GCS Error: {error_message}")
    return sorted(videos), error_message

def download_gcs_blob(bucket_name, source_blob_name, destination_file_name):
    """Downloads a blob from the bucket."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        blob.download_to_filename(destination_file_name)
        return True, None
    except Exception as e:
        error_msg = f"Error downloading GCS blob {source_blob_name}: {e}"
        print(error_msg)
        return False, error_msg

def upload_gcs_blob(bucket_name, source_file_name, destination_blob_name):
    """Uploads a file to the bucket."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        return True, None
    except Exception as e:
        error_msg = f"Error uploading GCS blob {destination_blob_name}: {e}"
        print(error_msg)
        return False, error_msg

# --- Streamlit App UI ---
st.set_page_config(layout="wide")
st.title("🎬 Gemini Trailer Assistant v2")


def reset_default_gcs_selection_flag_on_change():
    """Resets flags and selections when GCS config changes for Tab 2."""
    if 'default_gcs_selection_applied' in st.session_state:
        st.session_state.default_gcs_selection_applied = False
        print("[DEBUG app.py] reset_default_gcs_selection_flag_on_change: default_gcs_selection_applied set to False")
    if 'multiselect_gcs_videos_for_metadata' in st.session_state:
        st.session_state.multiselect_gcs_videos_for_metadata = []
        print("[DEBUG app.py] reset_default_gcs_selection_flag_on_change: multiselect_gcs_videos_for_metadata cleared")
# --- Sidebar for GCS Configuration ---
st.sidebar.header("⚙️ Global Configurations")

# Update session state from text_input and use session_state as the source of truth
st.session_state.GCS_BUCKET_NAME = st.sidebar.text_input(
    "GCS Bucket Name:",
    value=st.session_state.GCS_BUCKET_NAME,
    key="cfg_gcs_bucket_name",
    on_change=reset_default_gcs_selection_flag_on_change
)
st.session_state.GEMINI_API_KEY = st.sidebar.text_input(
    "Gemini API Key:",
    value=st.session_state.GEMINI_API_KEY,
    type="password",
    key="cfg_gemini_api_key"
)
st.session_state.AI_MODEL_NAME = st.sidebar.text_input(
    "AI Model Name:",
    value=st.session_state.AI_MODEL_NAME,
    key="cfg_ai_model_name"
)

st.sidebar.subheader("Temporary Local Directories")
st.session_state.TEMP_SPLIT_OUTPUT_DIR = st.sidebar.text_input(
    "Split Videos Output Dir (Tab 1):",
    value=st.session_state.TEMP_SPLIT_OUTPUT_DIR,
    key="cfg_temp_split_output_dir"
)
st.session_state.METADATA_OUTPUT_DIR = st.sidebar.text_input(
    "Metadata Output Dir (Tab 2):",
    value=st.session_state.METADATA_OUTPUT_DIR,
    key="cfg_metadata_output_dir"
)
st.session_state.TEMP_CLIPS_OUTPUT_DIR_TAB5 = st.sidebar.text_input(
    "Temp Clips Output Dir (Tab 5):",
    value=st.session_state.TEMP_CLIPS_OUTPUT_DIR_TAB5,
    key="cfg_temp_clips_output_dir_tab5"
)
st.session_state.TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5 = st.sidebar.text_input(
    "Temp AI Individual Clips Dir (Tab 5):",
    value=st.session_state.TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5,
    key="cfg_temp_ai_clips_individual_output_dir_tab5"
)
st.session_state.TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5 = st.sidebar.text_input(
    "Temp AI Joined Video Dir (Tab 5):",
    value=st.session_state.TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5,
    key="cfg_temp_ai_video_joined_output_dir_tab5"
)

st.sidebar.subheader("GCS Folder Prefixes")
st.session_state.GCS_PROCESSED_VIDEO_PREFIX = st.sidebar.text_input(
    "Processed Videos Prefix (Tabs 2, 5):",
    value=st.session_state.GCS_PROCESSED_VIDEO_PREFIX,
    key="cfg_gcs_processed_video_prefix",
    on_change=reset_default_gcs_selection_flag_on_change
)
st.session_state.GCS_METADATA_PREFIX_TAB5 = st.sidebar.text_input(
    "Metadata Prefix (Tab 5):",
    value=st.session_state.GCS_METADATA_PREFIX_TAB5,
    key="cfg_gcs_metadata_prefix_tab5"
)
st.session_state.GCS_OUTPUT_CLIPS_PREFIX_TAB5 = st.sidebar.text_input(
    "Output Clips Prefix (Tab 5):",
    value=st.session_state.GCS_OUTPUT_CLIPS_PREFIX_TAB5,
    key="cfg_gcs_output_clips_prefix_tab5"
)

# Re-create directories if changed by user input
# Note: This is a simplified approach. For production, consider more robust handling.
os.makedirs(st.session_state.METADATA_OUTPUT_DIR, exist_ok=True)
os.makedirs(st.session_state.TEMP_SPLIT_OUTPUT_DIR, exist_ok=True)
os.makedirs(st.session_state.TEMP_CLIPS_OUTPUT_DIR_TAB5, exist_ok=True)
os.makedirs(st.session_state.TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5, exist_ok=True)
os.makedirs(st.session_state.TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5, exist_ok=True)


# Conditional GCS/Gemini checks
gcs_ready = bool(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
# Gemini readiness now depends on the API key from session state
gemini_api_key_from_input = st.session_state.get("GEMINI_API_KEY", "")
gemini_ready = bool(gemini_api_key_from_input)

if not gcs_ready:
    st.sidebar.warning("⚠️ `GOOGLE_APPLICATION_CREDENTIALS` not set. GCS features may use dummy data or fail.")

if not gemini_ready:
    st.sidebar.warning("⚠️ Gemini API Key not provided in sidebar. Gemini features may fail.")
else:
    # Configure Gemini if the key is provided
    # This assumes get_model.py will have a function like configure_genai
    # For now, we'll just print a message. The actual call will be added
    # once get_model.py is updated.
    try:
        import get_model # To ensure it's loaded
        if hasattr(get_model, 'configure_genai_with_key'):
             get_model.configure_genai_with_key(gemini_api_key_from_input)
             st.sidebar.success("Gemini configured with provided API key.")
        elif gemini_api_key_from_input == CONFIG_KEYS["GEMINI_API_KEY"]: # Default key
             # If using default key, assume get_model.py handles it on import
             st.sidebar.info("Using default Gemini configuration.")
        else:
            # If key is provided but no configure function, it might be an issue
            # Or get_model.py needs to be adapted to re-configure
            genai.configure(api_key=gemini_api_key_from_input) # Direct configuration
            st.sidebar.success("Gemini re-configured with new API key directly.")


    except Exception as e:
        st.sidebar.error(f"Error configuring Gemini: {e}")


# --- Main Area ---
tab1_title = "Step 1: Video Split (Local)"
tab2_title = "Step 2: Metadata Generation (GCS)"
tab3_title = "Step 3: Clips Generation (GCS)"
tab4_title = "Step 4: Video Joining"
tab5_title = "Step 5: Generate Clips with AI"

tab1_ui, tab2_ui, tab3_ui, tab4_ui, tab5_ui = st.tabs([tab1_title, tab2_title, tab3_title, tab4_title, tab5_title])

with tab1_ui:
    render_tab1(
        temp_split_output_dir_param=st.session_state.TEMP_SPLIT_OUTPUT_DIR,
        allowed_video_extensions_param=ALLOWED_VIDEO_EXTENSIONS
    ) # ALLOWED_VIDEO_EXTENSIONS is global

with tab2_ui:
    print("DEBUG: Checking GCS config for render_tab2 call:")
    print(f"  GCS_BUCKET_NAME: {st.session_state.get('GCS_BUCKET_NAME')}")
    print(f"  GCS_PROCESSED_VIDEO_PREFIX (input for videos): {st.session_state.get('GCS_PROCESSED_VIDEO_PREFIX')}")
    print(f"  GCS_METADATA_PREFIX_TAB5 (used for Tab 2 metadata output prefix): {st.session_state.get('GCS_METADATA_PREFIX_TAB5')}")
    print(f"  METADATA_OUTPUT_DIR (local): {st.session_state.get('METADATA_OUTPUT_DIR')}")
    render_tab2(
        gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME,
        gcs_prefix_param=st.session_state.GCS_PROCESSED_VIDEO_PREFIX, # Formerly PROCESSED_GCS_FOLDER_NAME
        gemini_ready=gemini_ready,
        metadata_output_dir_global=st.session_state.METADATA_OUTPUT_DIR, # Formerly METADATA_OUTPUT_DIR
        gemini_api_key_global=st.session_state.GEMINI_API_KEY, # Formerly gemini_api_key_value
        ai_model_name_global=st.session_state.AI_MODEL_NAME,
        concurrent_api_calls_limit=CONCURRENT_API_CALLS_LIMIT,
        allowed_video_extensions_global=ALLOWED_VIDEO_EXTENSIONS,
        gcs_metadata_bucket_name=st.session_state.GCS_BUCKET_NAME, # Assuming metadata bucket is same as main
        gcs_output_metadata_prefix_param=st.session_state.GCS_METADATA_PREFIX_TAB5 # Use existing key for Tab 5
    )

with tab3_ui:
    render_tab3(gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME) # Add other params if needed

with tab4_ui:
    render_tab4(gcs_bucket_name=st.session_state.GCS_BUCKET_NAME) # Add other params if needed

with tab5_ui:
    render_tab5(
        gcs_bucket_name_param=st.session_state.GCS_BUCKET_NAME,
        gemini_api_key_param=st.session_state.GEMINI_API_KEY,
        ai_model_name_param=st.session_state.AI_MODEL_NAME,
        temp_clips_output_dir_param=st.session_state.TEMP_CLIPS_OUTPUT_DIR_TAB5,
        temp_ai_clips_individual_output_dir_param=st.session_state.TEMP_AI_CLIPS_INDIVIDUAL_OUTPUT_DIR_TAB5,
        temp_ai_video_joined_output_dir_param=st.session_state.TEMP_AI_VIDEO_JOINED_OUTPUT_DIR_TAB5,
        gcs_processed_video_prefix_param=st.session_state.GCS_PROCESSED_VIDEO_PREFIX,
        gcs_metadata_prefix_param=st.session_state.GCS_METADATA_PREFIX_TAB5,
        gcs_output_clips_prefix_param=st.session_state.GCS_OUTPUT_CLIPS_PREFIX_TAB5,
        gemini_ready_param=gemini_ready
    )

st.sidebar.markdown("---")
# Any other global sidebar elements can remain here