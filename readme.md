# Gemini Trailer Assistant

## Project Overview

The Gemini Trailer Assistant is a powerful Streamlit application designed to streamline the process of creating video trailers and clips from longer video files. It leverages the capabilities of Google's Gemini AI for intelligent content analysis and decision-making, combined with robust video processing using FFmpeg. The application provides a step-by-step workflow, from splitting a source video into manageable chunks to generating AI-powered trailer sequences.

The entire process is organized into a series of tabs, each dedicated to a specific stage of the workflow, providing a user-friendly interface for a complex task.

## Features

The application is divided into five main tabs, each with a specific set of features:

### Tab 1: Video Split (Local)

*   **Upload and Split**: Users can upload a video file directly in the app.
*   **Custom Segment Duration**: Specify the duration (in minutes) for each video chunk.
*   **Local Processing**: The splitting process is handled locally using `ffmpeg-python` for efficiency and speed.
*   **Progress Tracking**: A progress bar and status messages keep the user informed during the splitting process.
*   **Desktop App**: A downloadable, standalone Tkinter application (`video_splitter.py`) is provided for splitting very large files locally without browser limitations.

### Tab 2: Metadata Generation (GCS)

*   **GCS Integration**: Lists video files directly from a specified Google Cloud Storage (GCS) bucket and prefix.
*   **Batch Processing**: Select multiple video chunks to be processed in a single batch.
*   **AI-Powered Analysis**: Utilizes the Gemini AI model to analyze the video content (visuals, dialogue, sound) of each chunk.
*   **Customizable Prompts**: Users can edit the prompt sent to the Gemini AI to tailor the analysis to their specific needs (e.g., focusing on specific characters, themes, or emotional tones).
*   **Concurrent API Calls**: Processes multiple videos in parallel to speed up metadata generation.
*   **Metadata Storage**: The generated metadata (in JSON format) is saved to a local directory and automatically uploaded to a specified GCS bucket for persistence and use in later steps.

### Tab 3: Clips Generation (GCS)

*   **Metadata-Driven Clip Creation**: This tab uses the metadata files generated in Step 2 to create video clips.
*   **GCS Metadata Browser**: Lists and displays the content of metadata files stored in GCS.
*   **Clip Detail Extraction**:
    *   Extract clip details (source video and timestamps) from a single selected metadata file.
    *   Extract and combine clip details from *all* available metadata files in GCS.
*   **Manual Editing**: The extracted clip list can be manually edited in a text area before generation.
*   **FFmpeg-based Clipping**: Uses `ffmpeg-python` to precisely cut the clips from the source videos based on the timestamps.
*   **GCS Integration**: Downloads the source videos from GCS for clipping and uploads the final clips back to a specified GCS folder.

### Tab 4: Video Joining

*   **"Mini CapCut" Interface**: A simple, visual interface for stitching video clips together.
*   **GCS Clip Browser**: Displays video clips from a specified GCS `clips/` folder.
*   **Selection and Ordering**: Users can select multiple clips, and the order of selection dictates the final sequence.
*   **FFmpeg Concatenation**: Joins the selected clips into a single video file.
*   **GCS Upload**: The final stitched video is uploaded to a `joined_clips/` folder in the GCS bucket.

### Tab 5: Generate Clips with AI

*   **End-to-End AI Workflow**: This tab automates the creation of a trailer from the generated metadata.
*   **Load All Metadata**: Loads the raw content from all metadata files in GCS.
*   **AI Sequencing Prompt**: Users provide a high-level prompt to the Gemini AI, instructing it on the desired trailer characteristics (e.g., length, emotional arc, pacing).
*   **AI-Powered Clip Selection**: The Gemini AI analyzes the combined metadata and selects a sequence of clips to create a compelling trailer.
*   **Automated Clip Generation**: The application then automatically:
    1.  Downloads the required source videos from GCS.
    2.  Generates the individual clips selected by the AI using FFmpeg.
    3.  Uploads the individual clips to GCS.
    4.  Stitches the individual clips together into a final trailer.
*   **Download Final Video**: The final, AI-generated trailer is made available for download.

## Setup and Installation

To run this application locally, follow these steps:

1.  **Install Streamlit**: If you don't have Streamlit installed, you can install it using pip:
    ```bash
    pip install streamlit
    ```

2.  **Clone the Repository**:
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

3.  **Install Dependencies**: It is highly recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
    *Note: The `requirements.txt` file is included in this repository and contains all other necessary packages.*

4.  **Install FFmpeg**: The video processing functionalities depend on FFmpeg. You must have it installed on your system and accessible in your system's PATH.
    *   **macOS (using Homebrew)**: `brew install ffmpeg`
    *   **Ubuntu/Debian**: `sudo apt update && sudo apt install ffmpeg`
    *   **Windows**: Download the executable from the [official FFmpeg website](https://ffmpeg.org/download.html) and add it to your system's PATH.

5.  **Google Cloud Authentication**: The application needs to authenticate with Google Cloud to access GCS and Gemini.
    *   Install the Google Cloud CLI: [gcloud CLI installation guide](https://cloud.google.com/sdk/docs/install).
    *   Log in with your Google account:
        ```bash
        gcloud auth application-default login
        ```
    This command creates a credentials file that the application will automatically use.

6.  **Run the Streamlit Application**:
    *   Once all dependencies are installed and authentication is complete, you can run the app with the following command:
        ```bash
        streamlit run app.py
        ```
    *   The application will open in your default web browser.

## Configuration

Before running the application, ensure the following configurations are set:

1.  **GCS Bucket**: You need a GCS bucket to store your video files, metadata, and generated clips. You can create one through the [Google Cloud Console](https://console.cloud.google.com/storage/browser).
2.  **Gemini API Key**: You need a Gemini API key. You can obtain one from the [Google AI Studio](https://aistudio.google.com/app/apikey).
3.  **Application Configuration**: The application is configured via the sidebar in the UI. Key configurations include:
    *   **GCS Bucket Name**: The name of your GCS bucket.
    *   **Gemini API Key**: Your Gemini API key.
    *   **AI Model Name**: The specific Gemini model to use (e.g., `gemini-2.5-pro`).
    *   **Local and GCS Directories**: The paths for temporary local storage and GCS prefixes can also be configured.

## Workflow

Here is a typical workflow for using the Gemini Trailer Assistant:

1.  **Step 1: Split Video**
    *   For smaller files, you can use the "Video Split" tab directly within the Streamlit application.
    *   For larger files, it is recommended to use the standalone `video_splitter.py` script:
        ```bash
        python video_splitter.py
        ```
        This will open a desktop application where you can select your video, set the segment duration, and choose an output directory.
    *   The split video parts will be saved to the `temp_split_output/` directory by default.

2.  **Step 1b: Upload to GCS**
    *   Manually upload the split video parts from the `temp_split_output/` directory to your GCS bucket, under the `processed/` prefix.

3.  **Step 2: Generate Metadata**
    *   Go to the "Metadata Generation" tab.
    *   Ensure your GCS bucket and the `processed/` prefix are correctly configured in the sidebar.
    *   The application will list the video files from GCS.
    *   Select the video files you want to analyze.
    *   (Optional) Customize the Gemini prompt to guide the AI's analysis.
    *   Click "Generate Metadata for Selected GCS Files". The AI will process each video and save the resulting metadata to the `metadata/` prefix in your GCS bucket.

4.  **Step 3 & 4: Manual Clip Generation and Joining (Optional)**
    *   If you want to manually create clips, go to the "Clips Generation" tab.
    *   Load metadata from GCS, extract clip details, and generate individual clips.
    *   Then, go to the "Video Joining" tab to stitch these manually created clips together.

5.  **Step 5: AI-Powered Trailer Generation**
    *   Go to the "Generate Clips with AI" tab.
    *   Click "Load All GCS Metadata (Raw)" to load all the metadata generated in Step 2.
    *   Review and edit the high-level prompt that will instruct the AI on how to assemble the trailer.
    *   Click "Generate Clips". The AI will return a list of clips to form the trailer.
    *   Review the AI's proposed clip list.
    *   Click "Generate AI Video". The application will create all the individual clips, stitch them together, and provide a download link for the final trailer.

## File Descriptions

*   **`app.py`**: The main entry point for the Streamlit application. It sets up the UI, tabs, and global configurations.
*   **`video_splitter.py`**: A standalone Tkinter-based desktop application for splitting large video files.
*   **`get_model.py`**: Handles the configuration of the Google Gemini AI model.
*   **`tabs/tab1_video_split.py`**: Contains the UI and logic for the "Video Split" tab.
*   **`tabs/tab2_metadata_generation.py`**: Contains the UI and logic for the "Metadata Generation" tab, including batch processing and Gemini API calls.
*   **`tabs/tab3_trailer_generation.py`**: Contains the UI and logic for the manual "Clips Generation" tab.
*   **`tabs/tab4_video_joining.py`**: Contains the UI and logic for the "Video Joining" tab.
*   **`tabs/tab5_generate_clips_ai.py`**: Contains the UI and logic for the AI-powered "Generate Clips with AI" tab.
*   **`temp_*/` directories**: Local directories used for temporary storage of split videos, metadata, and generated clips.