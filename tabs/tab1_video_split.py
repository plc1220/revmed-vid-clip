import streamlit as st
import os
import threading
import math
import ffmpeg # New import
from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx

# --- Constants (Consider moving to a central config if used by many tabs) ---
# ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv'] # Now passed as parameter

# --- Video Splitting Thread Target Function ---
def split_video_threaded(parent_ctx, uploaded_file_bytes, original_file_name, segment_duration_minutes=5, project_output_dir_param="./temp_split_output"): # Added project_output_dir_param
    if parent_ctx:
        add_script_run_ctx(threading.current_thread(), parent_ctx)

    st.session_state.split_progress = 0
    st.session_state.split_error_message = None
    st.session_state.split_success_message = None

    # Directory for moviepy's temporary processing files (e.g., intermediate audio)
    processing_temp_dir = "/tmp/video_processing_temp"
    os.makedirs(processing_temp_dir, exist_ok=True)

    # Directory within the project to save the final split segments
    # project_output_dir = "./temp_split_output" # Now passed as project_output_dir_param
    os.makedirs(project_output_dir_param, exist_ok=True)

    local_video_path = os.path.join(processing_temp_dir, original_file_name)
    video = None # Initialize video object

    try:
        # 1. Save uploaded video bytes to a temporary file for processing
        st.session_state.split_progress = 2 # Start progress
        with open(local_video_path, "wb") as f:
            f.write(uploaded_file_bytes)
        st.session_state.split_progress = 5 # Progress after saving

        # 2. Split video using ffmpeg-python
        try:
            probe = ffmpeg.probe(local_video_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if not video_stream or 'duration' not in video_stream:
                st.session_state.split_error_message = f"Could not get duration from video '{original_file_name}'."
                st.session_state.split_progress = 100
                return
            duration = float(video_stream['duration'])
        except ffmpeg.Error as e:
            st.session_state.split_error_message = f"ffmpeg.probe error on '{original_file_name}': {e.stderr.decode('utf8')}"
            st.session_state.split_progress = 100
            return

        if duration <= 0:
            st.session_state.split_error_message = f"Video '{original_file_name}' has zero or negative duration ({duration}s). Cannot split."
            st.session_state.split_progress = 100
            return

        segment_duration_seconds = segment_duration_minutes * 60
        num_segments = math.ceil(duration / segment_duration_seconds)
        saved_segment_paths = []

        for i in range(num_segments):
            if st.session_state.get('stop_splitting_requested', False):
                st.session_state.split_error_message = "Video splitting stopped by user."
                break

            start_time = i * segment_duration_seconds
            # For ffmpeg, -t is duration, or use -to for end time.
            # We'll calculate duration for each segment.
            current_segment_duration = min(segment_duration_seconds, duration - start_time)

            if current_segment_duration <= 0:
                print(f"Thread: Skipping segment {i+1} of {original_file_name} due to zero or negative calculated duration.")
                continue

            base_name, ext = os.path.splitext(original_file_name)
            segment_file_name = f"{base_name}_part_{i+1:03d}{ext}"
            local_segment_output_path = os.path.join(project_output_dir_param, segment_file_name)

            try:
                (
                    ffmpeg
                    .input(local_video_path, ss=start_time, t=current_segment_duration)
                    .output(local_segment_output_path, c='copy', avoid_negative_ts=1) # Attempt to copy codecs for speed
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                saved_segment_paths.append(local_segment_output_path)
            except ffmpeg.Error as e:
                # If 'copy' codec fails (e.g., format change or keyframe issues), try re-encoding
                st.warning(f"Codec copy failed for segment {i+1} of {original_file_name}: {e.stderr.decode('utf8')}. Trying re-encoding.")
                try:
                    (
                        ffmpeg
                        .input(local_video_path, ss=start_time, t=current_segment_duration)
                        .output(local_segment_output_path, vcodec='libx264', acodec='aac', strict='experimental', avoid_negative_ts=1) # Re-encode
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True)
                    )
                    saved_segment_paths.append(local_segment_output_path)
                except ffmpeg.Error as e2:
                    st.session_state.split_error_message = f"Error splitting segment {i+1} of {original_file_name} (re-encode): {e2.stderr.decode('utf8')}"
                    # Optionally, break or log this specific segment failure and continue
                    print(st.session_state.split_error_message) # Log to console
                    break # Stop on first segment error for now
            
            st.session_state.split_progress = 5 + int(((i + 1) / num_segments) * 90)

        if st.session_state.get('stop_splitting_requested'):
            pass # Message already set
        elif st.session_state.get('split_error_message'):
            pass # Error message already set (e.g. from segment processing)
        elif not saved_segment_paths and num_segments > 0 :
             st.session_state.split_error_message = "No segments were successfully processed or saved."
        elif not saved_segment_paths and num_segments == 0: # Should be caught by duration check earlier
            st.session_state.split_success_message = f"Video '{original_file_name}' is shorter than one segment ({segment_duration_minutes} min), no splits created."
        else:
            st.session_state.split_success_message = f"Successfully split '{original_file_name}' into {len(saved_segment_paths)} parts and saved to '{project_output_dir_param}/'."

    except ffmpeg.Error as e: # Catch ffmpeg specific errors during probe or general setup
        st.session_state.split_error_message = f"An ffmpeg error occurred during video splitting of '{original_file_name}': {e.stderr.decode('utf8')}"
        import traceback
        traceback.print_exc()
    except Exception as e: # Catch other general exceptions
        st.session_state.split_error_message = f"An unexpected error occurred during video splitting of '{original_file_name}': {e}"
        import traceback
        traceback.print_exc()
    finally:
        # No video object to close like with moviepy
        if os.path.exists(local_video_path): # Clean up the temporary uploaded video file
            try:
                os.remove(local_video_path)
            except Exception as e_remove:
                print(f"Error removing temporary video file {local_video_path}: {e_remove}")

        st.session_state.split_progress = 100
        st.session_state.is_splitting = False
        
        try:
            if os.path.exists(processing_temp_dir) and not os.listdir(processing_temp_dir):
                os.rmdir(processing_temp_dir)
        except Exception as e_clean_processing:
            print(f"Error cleaning up processing temp directory {processing_temp_dir}: {e_clean_processing}")
        st.rerun()

def render_tab1(temp_split_output_dir_param: str, allowed_video_extensions_param: list):
    st.header("Step 1: Video Split")

    st.info(
        "Do not use the online version, it may not work for large videos. "
        "For large videos, please use the desktop version. "
        "You can download the `video_splitter.py` script below."
    )

    video_splitter_script_content = """import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from moviepy import VideoFileClip
import os
import math

class VideoSplitterApp:
    def __init__(self, master):
        self.master = master
        master.title("Video Splitter")

        self.file_path_label = tk.Label(master, text="Video File:", fg="#000000")
        self.file_path_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.file_path_entry = tk.Entry(master, width=50, fg="#000000", bg="#FFFFFF")
        self.file_path_entry.grid(row=0, column=1, padx=5, pady=5)

        self.browse_button = tk.Button(master, text="Browse", command=self.browse_file, fg="#000000")
        self.browse_button.grid(row=0, column=2, padx=5, pady=5)

        self.duration_label = tk.Label(master, text="Segment Duration (minutes):", fg="#000000")
        self.duration_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)

        self.duration_entry = tk.Entry(master, width=10, fg="#000000", bg="#FFFFFF")
        self.duration_entry.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.duration_entry.insert(0, "10") # Default to 10 minutes

        self.output_dir_label = tk.Label(master, text="Output Directory:", fg="#000000")
        self.output_dir_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

        self.output_dir_entry = tk.Entry(master, width=50, fg="#000000", bg="#FFFFFF")
        self.output_dir_entry.grid(row=2, column=1, padx=5, pady=5)
        self.output_dir_entry.insert(0, "./temp_split_output/")
 
        self.split_button = tk.Button(master, text="Split Video", command=self.split_video, fg="#000000")
        self.split_button.grid(row=3, column=0, columnspan=3, pady=10) # Adjusted row

        self.progress_bar = ttk.Progressbar(master, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.grid(row=4, column=0, columnspan=3, pady=5) # Adjusted row
        
        self.status_label = tk.Label(master, text="", fg="#000000")
        self.status_label.grid(row=5, column=0, columnspan=3, pady=5) # Adjusted row

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select a video file",
            filetypes=(("MP4 files", "*.mp4"), ("AVI files", "*.avi"), ("MOV files", "*.mov"), ("All files", "*.*"))
        )
        if file_path:
            self.file_path_entry.delete(0, tk.END)
            self.file_path_entry.insert(0, file_path)
            self.status_label.config(text=f"Selected file: {os.path.basename(file_path)}")

    def split_video(self):
        video_path = self.file_path_entry.get()
        if not video_path:
            messagebox.showerror("Error", "Please select a video file.")
            return

        if not os.path.exists(video_path):
            messagebox.showerror("Error", f"File not found: {video_path}")
            return

        try:
            segment_duration_min = int(self.duration_entry.get())
            if segment_duration_min <= 0:
                raise ValueError("Duration must be positive.")
            segment_duration_sec = segment_duration_min * 60
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for segment duration.")
            return

        self.status_label.config(text="Processing... please wait.")
        self.master.update_idletasks() # Update GUI to show status

        try:
            # Load once to get duration and calculate segments
            initial_clip_for_duration = VideoFileClip(video_path)
            total_duration_sec = initial_clip_for_duration.duration
            initial_clip_for_duration.close() # Close it immediately after getting duration
            num_segments = math.ceil(total_duration_sec / segment_duration_sec)

            output_dir_path = self.output_dir_entry.get().strip()
            if not output_dir_path:
                output_dir_path = "./temp_split_output/"
            output_dir = os.path.abspath(output_dir_path)
            os.makedirs(output_dir, exist_ok=True)

            base_filename = os.path.splitext(os.path.basename(video_path))[0]

            self.progress_bar["maximum"] = num_segments
            self.progress_bar["value"] = 0
            self.master.update_idletasks()

            for i in range(num_segments):
                start_time = i * segment_duration_sec
                end_time = min((i + 1) * segment_duration_sec, total_duration_sec)
                
                self.status_label.config(text=f"Processing segment {i+1} of {num_segments}...")
                self.master.update_idletasks()

                # Ensure end_time does not exceed video duration for the last segment
                if end_time > total_duration_sec:
                    end_time = total_duration_sec

                # Skip if start_time is beyond or at video duration (can happen with rounding)
                if start_time >= total_duration_sec:
                    self.progress_bar["value"] = i + 1 # Still update progress for skipped segment
                    self.master.update_idletasks()
                    continue
                
                # Re-open the video for each segment to ensure a fresh process
                video_for_segment = None # Initialize to ensure it's defined for finally block
                try:
                    video_for_segment = VideoFileClip(video_path)
                    segment = video_for_segment.subclipped(start_time, end_time)
                    output_filename = os.path.join(output_dir, f"{base_filename}_part{i+1}.mp4")

                    if os.path.exists(output_filename):
                        replace = messagebox.askyesno(
                            "File Exists",
                            f"The file '{os.path.basename(output_filename)}' already exists.\\nDo you want to replace it?"
                        )
                        if not replace:
                            self.status_label.config(text=f"Skipped segment {i+1} (file exists).")
                            self.progress_bar["value"] = i + 1 # Still update progress for skipped segment
                            self.master.update_idletasks() # Update GUI AFTER progress bar value is set
                            segment.close() # Close the subclip if not writing
                            if video_for_segment:
                                video_for_segment.close() # Close the main clip for this iteration
                            continue
                    
                    # Use a specific codec if needed, e.g., libx264 for H.264
                    # You might need to adjust parameters based on your ffmpeg installation and desired output
                    segment.write_videofile(output_filename, codec="libx264", audio_codec="aac", logger=None)
                    segment.close()
                
                finally:
                    if video_for_segment:
                        video_for_segment.close() # Ensure clip is closed even if error occurs during write

                self.progress_bar["value"] = i + 1
                self.master.update_idletasks()
            
            # video.close() # Original video object is no longer held open through the loop
            self.status_label.config(text=f"Video split successfully! {num_segments} segments created in '{output_dir}'.")
            messagebox.showinfo("Success", f"Video split into {num_segments} segments.\\nFiles saved in: {output_dir}")
            self.progress_bar["value"] = 0 # Reset progress bar
        except Exception as e:
            self.status_label.config(text=f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred during splitting: {str(e)}")
            self.progress_bar["value"] = 0 # Reset progress bar


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoSplitterApp(root)
    root.mainloop()
"""
    st.download_button(
        label="📥 Download video_splitter.py",
        data=video_splitter_script_content,
        file_name="video_splitter.py",
        mime="text/x-python"
    )

    st.markdown("---") # Add a separator

    # Declare the file uploader and assign its returned value.
    # Streamlit uses the 'key' to manage the widget's state across reruns.
    uploaded_file_obj = st.file_uploader(
        "Upload a video file to split:",
        type=[ext.lstrip('.') for ext in allowed_video_extensions_param],
        key="uploaded_video_for_split_widget"
    )

    # Now, uploaded_file_obj directly holds the UploadedFile object or None.
    # st.session_state.uploaded_video_for_split_widget will also be updated by Streamlit.

    if uploaded_file_obj:
        st.write(f"Uploaded file: `{uploaded_file_obj.name}` ({uploaded_file_obj.size / (1024*1024):.2f} MB)")
        segment_duration_min = st.number_input("Max duration per chunk (minutes):", min_value=1, value=5, step=1, key="segment_duration_input")

        split_button_disabled = st.session_state.get('is_splitting', False)
        split_button = st.button("✂️ Split Video", disabled=split_button_disabled, key="split_video_button")

        if st.session_state.get('is_splitting', False):
            stop_splitting_button = st.button("🛑 Stop Splitting", key="stop_splitting_button")
            if stop_splitting_button:
                st.session_state.stop_splitting_requested = True
                st.warning("Stop request sent for video splitting. Finishing current segment...")

        if split_button and not st.session_state.get('is_splitting', False):
            st.session_state.is_splitting = True
            st.session_state.stop_splitting_requested = False
            st.session_state.split_progress = 0
            st.session_state.split_error_message = None
            st.session_state.split_success_message = None

            file_bytes = uploaded_file_obj.getvalue()
            original_filename = uploaded_file_obj.name

            ctx = get_script_run_ctx()
            st.session_state.splitting_thread = threading.Thread(
                target=split_video_threaded,
                args=(ctx, file_bytes, original_filename, segment_duration_min, temp_split_output_dir_param) # Pass the output dir
            )
            st.session_state.splitting_thread.start()
            st.rerun()
    else:
        st.info("Please upload a video file to enable splitting options.")

    if st.session_state.split_progress_bar_placeholder is None:
        st.session_state.split_progress_bar_placeholder = st.empty()

    if st.session_state.get('is_splitting', False):
        current_split_progress = st.session_state.get('split_progress', 0)
        st.session_state.split_progress_bar_placeholder.progress(current_split_progress, text=f"Splitting video... ({current_split_progress}%)")

    if st.session_state.get('split_error_message'):
        st.error(f"**Splitting Error:** {st.session_state.split_error_message}")
        st.session_state.split_progress_bar_placeholder.empty()
    if st.session_state.get('split_success_message'):
        st.success(st.session_state.split_success_message)
        st.session_state.split_progress_bar_placeholder.empty()