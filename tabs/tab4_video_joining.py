import streamlit as st
import os
import ffmpeg # New import
import re # For parsing timestamps
import tempfile # For creating temporary file list for concatenation
from google.cloud import storage
import datetime
import uuid # For unique temporary file names

# Define a temporary directory for downloaded clips and joined video
TEMP_DOWNLOAD_DIR = "temp_gcs_downloads"
TEMP_JOINED_DIR = "temp_gcs_joined"
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_JOINED_DIR, exist_ok=True)


def get_gcs_bucket(bucket_name):
    """Initializes and returns a GCS bucket object."""
    storage_client = storage.Client()
    return storage_client.bucket(bucket_name)

def list_gcs_clips(bucket, prefix):
    """Lists all blobs in a GCS bucket with the given prefix.
    Returns a list of dictionaries, each containing 'name' and 'url'.
    """
    blobs = bucket.list_blobs(prefix=prefix)
    clips_data = []
    for blob in blobs:
        # Ensure we are not listing items from subdirectories like 'joined_clips/' within 'clips/'
        if blob.name.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')) and '/' not in blob.name[len(prefix):]:
            # Generate a signed URL for the blob, valid for 1 hour
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(hours=1),
                method="GET",
            )
            clips_data.append({"name": blob.name, "filename": os.path.basename(blob.name), "url": url})
    return clips_data

def join_videos_gcs(bucket, selected_clips_data, output_gcs_prefix="joined_clips/"):
    """
    Downloads selected video clips from GCS, joins them using ffmpeg,
    and uploads the result back to GCS.
    selected_clips_data: List of dictionaries, each with at least a 'name' key for the GCS blob name.
    """
    if not selected_clips_data:
        st.warning("No clips selected for joining.")
        return None

    local_clip_paths = []
    temp_files_to_clean = []

    try:
        st.write("Downloading selected clips...")
        progress_bar_download = st.progress(0)
        for i, clip_data in enumerate(selected_clips_data):
            blob_name = clip_data['name']
            local_filename = os.path.join(TEMP_DOWNLOAD_DIR, os.path.basename(blob_name))
            blob = bucket.blob(blob_name)
            blob.download_to_filename(local_filename)
            local_clip_paths.append(local_filename)
            temp_files_to_clean.append(local_filename)
            progress_bar_download.progress((i + 1) / len(selected_clips_data))
        st.success("All selected clips downloaded.")

        # Create a temporary file list for ffmpeg concatenation
        concat_list_filename = os.path.join(TEMP_DOWNLOAD_DIR, f"concat_list_{uuid.uuid4().hex}.txt")
        with open(concat_list_filename, 'w') as f:
            for path in local_clip_paths:
                f.write(f"file '{os.path.abspath(path)}'\n") # ffmpeg needs absolute paths or paths relative to where it's run
        temp_files_to_clean.append(concat_list_filename)

        # Define output path for the joined video
        output_filename_base = f"stitched_video_{uuid.uuid4().hex}.mp4"
        local_joined_video_path = os.path.join(TEMP_JOINED_DIR, output_filename_base)
        temp_files_to_clean.append(local_joined_video_path)

        st.write("Stitching videos...")
        # Using ffmpeg-python to concatenate
        (
            ffmpeg
            .input(concat_list_filename, format='concat', safe=0)
            .output(local_joined_video_path, c='copy', vsync='vfr') # vsync=vfr can help with variable frame rate videos
            .run(overwrite_output=True, quiet=True)
        )
        st.success(f"Videos stitched successfully: {output_filename_base}")

        # Upload the joined video to GCS
        st.write("Uploading stitched video to GCS...")
        joined_video_gcs_path = os.path.join(output_gcs_prefix, output_filename_base)
        joined_blob = bucket.blob(joined_video_gcs_path)
        joined_blob.upload_from_filename(local_joined_video_path)
        
        # Generate a signed URL for the newly uploaded video
        joined_video_url = joined_blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=1),
            method="GET"
        )
        st.success(f"Stitched video uploaded to GCS: {joined_video_gcs_path}")
        return joined_video_gcs_path, joined_video_url

    except Exception as e:
        st.error(f"Error during video joining process: {e}")
        return None, None
    finally:
        # Clean up temporary files
        for f_path in temp_files_to_clean:
            if os.path.exists(f_path):
                os.remove(f_path)
        st.info("Cleaned up temporary files.")


def parse_timecode(timecode_str):
    """Converts HH:MM:SS or MM:SS or SS string to seconds."""
    parts = list(map(int, timecode_str.split(':')))
    if len(parts) == 3: # HH:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2: # MM:SS
        return parts[0] * 60 + parts[1]
    elif len(parts) == 1: # SS
        return parts[0]
    else:
        raise ValueError(f"Invalid timecode format: {timecode_str}")

def render_tab4(gcs_bucket_name="your-gcs-bucket-name"):
    st.header("🎬 Mini CapCut - Video Stitcher")
    st.markdown("Select clips from GCS, then stitch them together into a new video.")

    if 'selected_clips_for_joining' not in st.session_state:
        st.session_state.selected_clips_for_joining = []
    if 'joined_video_url_tab4' not in st.session_state:
        st.session_state.joined_video_url_tab4 = None
    if 'joined_video_gcs_path_tab4' not in st.session_state:
        st.session_state.joined_video_gcs_path_tab4 = None


    gcs_bucket_name_to_use = gcs_bucket_name
    if not gcs_bucket_name_to_use or gcs_bucket_name_to_use == "your-gcs-bucket-name":
        st.sidebar.subheader("GCS Configuration")
        gcs_bucket_name_input = st.sidebar.text_input(
            "Enter GCS Bucket Name:",
            value=st.session_state.get("gcs_bucket_name_global", gcs_bucket_name_to_use),
            key="gcs_bucket_name_tab4_input"
        )
        if gcs_bucket_name_input:
            gcs_bucket_name_to_use = gcs_bucket_name_input
            st.session_state.gcs_bucket_name_global = gcs_bucket_name_input # Save globally if changed
        else:
            st.warning("Please enter a GCS Bucket Name in the sidebar to load clips.")
            return

    clips_gcs_prefix = "clips/"
    joined_clips_gcs_prefix = "joined_clips/" # For storing stitched videos

    try:
        bucket = get_gcs_bucket(gcs_bucket_name_to_use)
        clips_data = list_gcs_clips(bucket, clips_gcs_prefix)

        if not clips_data:
            st.info(f"No video clips found in GCS bucket '{gcs_bucket_name_to_use}' under prefix '{clips_gcs_prefix}'.")
            st.info("Please ensure there are .mp4, .mov, .avi, or .mkv files directly under this prefix (not in subfolders).")
            return

        st.subheader(f"Available Clips from gs://{gcs_bucket_name_to_use}/{clips_gcs_prefix}")
        st.markdown("Select the clips you want to join. The order of selection will be the order of joining.")

        # --- Clip Selection Area ---
        selected_this_run = [] # To track selections in the current UI render pass

        num_columns = st.slider("Number of columns for clip display:", 1, 5, 3)
        cols = st.columns(num_columns)
        
        # Keep track of currently selected GCS blob names for checkbox state
        # This ensures checkboxes reflect the st.session_state.selected_clips_for_joining
        currently_selected_blob_names = [clip['name'] for clip in st.session_state.selected_clips_for_joining]

        for i, clip_info in enumerate(clips_data):
            with cols[i % num_columns]:
                st.video(clip_info["url"], format="video/mp4", start_time=0)
                st.caption(clip_info["filename"])
                
                # Checkbox state is determined by whether the clip_info['name'] is in currently_selected_blob_names
                is_selected = clip_info['name'] in currently_selected_blob_names
                
                # The key for the checkbox must be unique for each clip
                if st.checkbox(f"Select {clip_info['filename']}", value=is_selected, key=f"select_{clip_info['name']}"):
                    if not is_selected: # If it wasn't selected before, and now it is
                        # Add to session state if not already there (to maintain order)
                        if clip_info not in st.session_state.selected_clips_for_joining:
                             st.session_state.selected_clips_for_joining.append(clip_info)
                    selected_this_run.append(clip_info) # Add to current run selection
                else: # If checkbox is unchecked
                    if is_selected: # If it was selected before, and now it is not
                        # Remove from session state
                        st.session_state.selected_clips_for_joining = [
                            c for c in st.session_state.selected_clips_for_joining if c['name'] != clip_info['name']
                        ]
        
        # Display selected clips in order
        if st.session_state.selected_clips_for_joining:
            st.subheader("Selected Clips (in order of joining):")
            ordered_filenames = [f"{idx+1}. {clip['filename']}" for idx, clip in enumerate(st.session_state.selected_clips_for_joining)]
            st.write(" -> ".join(ordered_filenames))
        else:
            st.info("No clips selected yet. Check the boxes above to select clips.")

        # --- Stitching Button and Logic ---
        if st.button("🎬 Stitch Selected Clips", disabled=not st.session_state.selected_clips_for_joining):
            with st.spinner("Processing... This may take a while depending on clip sizes and numbers."):
                st.session_state.joined_video_gcs_path_tab4, st.session_state.joined_video_url_tab4 = join_videos_gcs(
                    bucket,
                    st.session_state.selected_clips_for_joining,
                    output_gcs_prefix=joined_clips_gcs_prefix
                )
            if st.session_state.joined_video_url_tab4:
                st.success("Video stitching complete!")
                # Clear selection after successful stitching
                # st.session_state.selected_clips_for_joining = [] # Optional: clear selection
            else:
                st.error("Video stitching failed. Check the error messages above.")
        
        # Display the joined video if available
        if st.session_state.joined_video_url_tab4:
            st.subheader("🎉 Joined Video")
            st.video(st.session_state.joined_video_url_tab4)
            st.markdown(f"GCS Path: `gs://{gcs_bucket_name_to_use}/{st.session_state.joined_video_gcs_path_tab4}`")
            if st.button("Clear Joined Video and Selection"):
                st.session_state.joined_video_url_tab4 = None
                st.session_state.joined_video_gcs_path_tab4 = None
                st.session_state.selected_clips_for_joining = []
                st.rerun()


    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.error("Please ensure your GCS credentials are set up correctly (e.g., GOOGLE_APPLICATION_CREDENTIALS environment variable) and the bucket exists.")