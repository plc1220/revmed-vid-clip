import tkinter as tk
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
                            f"The file '{os.path.basename(output_filename)}' already exists.\nDo you want to replace it?"
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
            messagebox.showinfo("Success", f"Video split into {num_segments} segments.\nFiles saved in: {output_dir}")
            self.progress_bar["value"] = 0 # Reset progress bar
        except Exception as e:
            self.status_label.config(text=f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred during splitting: {str(e)}")
            self.progress_bar["value"] = 0 # Reset progress bar


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoSplitterApp(root)
    root.mainloop()