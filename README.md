# Rev-Med Video Assistant

The Rev-Med Video Assistant is a comprehensive tool for processing, analyzing, and editing video content. It combines a powerful FastAPI backend for video and AI processing with an intuitive Streamlit user interface for managing the workflow. The application is designed to automate tasks such as splitting long videos into manageable segments, generating descriptive metadata using AI, and creating new clips based on that metadata or specific AI-driven prompts.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Components](#core-components)
  - [FastAPI Backend](#fastapi-backend)
  - [Streamlit UI](#streamlit-ui)
  - [Google Cloud Storage (GCS)](#google-cloud-storage-gcs)
  - [AI Service (Google Gemini)](#ai-service-google-gemini)
- [Setup and Installation](#setup-and-installation)
  - [Prerequisites](#prerequisites)
  - [Configuration](#configuration)
  - [Running the Application](#running-the-application)
- [API Documentation (Swagger UI)](#api-documentation-swagger-ui)
- [User Interface Workflow](#user-interface-workflow)
  - [Tab 1: Video Split](#tab-1-video-split)
  - [Tab 2: Metadata Generation](#tab-2-metadata-generation)
  - [Tab 3: Clip Generation](#tab-3-clip-generation)
  - [Tab 4: Video Joining](#tab-4-video-joining)
  - [Tab 5: AI Clip Generation](#tab-5-ai-clip-generation)
- [Running Tests](#running-tests)

## Architecture Overview

The application consists of two main parts:

1.  **Backend API**: A FastAPI server that handles all heavy lifting, including video processing (splitting, clipping, joining), interaction with Google Cloud Storage, and making calls to the Google Gemini AI for content analysis. It operates asynchronously to manage long-running tasks.
2.  **Frontend UI**: A Streamlit web application that provides a user-friendly interface to interact with the backend. Users can upload videos, initiate processing jobs, and view the results through this interface.

## Core Components

### FastAPI Backend

The backend is the engine of the application. It exposes a series of RESTful endpoints to handle different stages of the video processing pipeline.

-   **Video Upload**: Receives video files and uploads them to GCS.
-   **Video Splitting**: Splits a source video into smaller segments of a specified duration.
-   **Metadata Generation**: Analyzes video segments using the Gemini AI to generate structured metadata (e.g., identifying key moments, transcribing speech).
-   **Clip Generation**: Creates new video clips from segments based on timestamps or AI-driven selections.
-   **Video Joining**: Combines multiple clips into a single video file.
-   **Job Status Tracking**: Manages and reports the status of background processing jobs.

### Streamlit UI

The Streamlit application provides a step-by-step workflow through a series of tabs. It communicates with the FastAPI backend to trigger jobs and display results. The sidebar allows for global configuration of settings like GCS bucket names and API keys.

### Google Cloud Storage (GCS)

GCS is used as the primary storage solution for all files, including:
- Original uploaded videos.
- Processed video segments.
- Generated metadata files (JSON).
- Final output clips and joined videos.

### AI Service (Google Gemini)

The application leverages Google's Gemini model for its AI capabilities. It is used to:
- Analyze video content and generate descriptive metadata.
- Intelligently select relevant clips from a video based on a user's prompt.

## Setup and Installation

### Prerequisites

1.  **Python Environment**: Ensure you have Python 3.9+ installed.
2.  **Install Dependencies**: Install all required Python packages.
    ```bash
    pip install -r requirements.txt
    ```
3.  **Install Playwright Browsers**: Required for running the UI tests.
    ```bash
    playwright install
    ```

### Configuration

Create a `.env` file in the root directory of the project and add the following environment variables.

```
GEMINI_API_KEY="YOUR_GOOGLE_GEMINI_API_KEY"
DEFAULT_GCS_BUCKET="your-default-gcs-bucket-name"
```

You will also need to set up Google Cloud authentication. Ensure your GCS credentials JSON file is available and the path is set in your environment if required by your setup.

### Running the Application

The application requires both the backend and frontend servers to be running simultaneously.

1.  **Run the Backend API:**
    ```bash
    uvicorn api.main:app --reload
    ```
    The API will be available at `http://127.0.0.1:8000`.

2.  **Run the Streamlit App:**
    ```bash
    streamlit run app.py
    ```
    The UI will be accessible in your browser, typically at `http://localhost:8501`.

## Deployment

[![Open in Cloud Shell](https://gstatic.com/cloudssh/images/open-btn.svg)](https://shell.cloud.google.com/cloudshell/editor?cloudshell_git_repo=https://github.com/plc1220/revmed-vid-clip.git&cloudshell_tutorial=README.md)

Click the button above to deploy this application to Google Cloud Run. This will open Google Cloud Shell, clone the repository, and guide you through the deployment process.

## API Documentation (Swagger UI)

The FastAPI backend automatically generates interactive API documentation using Swagger UI. This is the best place to explore and test the API endpoints directly.

Once the backend server is running, you can access the Swagger UI at:
[**http://127.0.0.1:8000/docs**](http://127.0.0.1:8000/docs)

The documentation provides detailed information about each endpoint, including required parameters, request bodies, and response models.

## User Interface Workflow

The Streamlit UI guides you through the video processing pipeline with a series of tabs.

### Tab 1: Video Split

-   **Function**: Upload a video file and split it into smaller, equal-length segments.
-   **Process**: Select a video file, specify the desired segment duration (in seconds), and click "Start Splitting". The backend will process the video and store the segments in GCS.

### Tab 2: Metadata Generation

-   **Function**: Analyze the video segments generated in the previous step to create structured metadata.
-   **Process**: Select the folder containing the video segments. The application uses the Gemini AI to analyze each segment and produces a consolidated JSON metadata file.

### Tab 3: Clip Generation

-   **Function**: Manually create clips from video segments based on the generated metadata.
-   **Process**: This tab allows you to review the metadata and specify start/end timestamps to create clips from the source segments.

### Tab 4: Video Joining

-   **Function**: Combine multiple generated clips into a single, final video.
-   **Process**: Select the clips you want to include. The application will join them in the specified order and save the final video to GCS.

### Tab 5: AI Clip Generation

-   **Function**: Automatically generate a sequence of clips based on a high-level user prompt.
-   **Process**: Select a metadata file and provide a prompt (e.g., "create a 30-second trailer focusing on the exciting moments"). The AI will analyze the metadata, select the most relevant segments, and generate the final clips.

## Running Tests

To ensure the end-to-end workflow is functioning correctly, you can run the included UI test. Make sure both the backend and frontend servers are running before executing the test.

```bash
pytest ui_test.py
```

The test automates the entire UI workflow, from uploading a video to joining the final clips, and verifies that each step completes successfully.
