import os
import google.genai as genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Tuple, List
from schemas import TrailerClipMetadata
import logging

# --- Gemini Client Initialization ---
# Switch to Vertex AI client for GCS URI support
try:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")
    if not project_id or not location:
        raise ValueError("GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION environment variables must be set to use the Vertex AI client.")
    
    client = genai.Client(vertexai=True, project=project_id, location=location)
    logging.info("Successfully initialized Vertex AI client.")
except Exception as e:
    import traceback
    logging.error(f"Failed to initialize Genai Client: {e}")
    traceback.print_exc()
    client = None

# --- API Call Logic ---

@retry(
    wait=wait_exponential(multiplier=1, min=5, max=60),
    stop=stop_after_attempt(5)
)
async def generate_content_async(prompt: str, gcs_video_uri: str, model_name: str) -> Tuple[str, str]:
    """
    Calls the Gemini API asynchronously to generate content based on a video and prompt.
    Returns a tuple of (response_text, error_message_string).
    """
    if not client:
        return "", "Genai Client is not initialized."

    try:
        # Prepare the video file part for the API call
        video_part = types.Part.from_uri(
            file_uri=gcs_video_uri,
            mime_type="video/mp4",
        )
        
        # The content for the API call, including the prompt and the video
        contents = [prompt, video_part]
        
        # Generation and safety settings
        # Generate the JSON schema from the Pydantic model.
        trailer_clip_schema = TrailerClipMetadata.model_json_schema()
        # The API expects a list of these objects, so we define the response schema as an array of that object schema.
        response_schema_for_list = {
            "type": "array",
            "items": trailer_clip_schema
        }

        config = types.GenerateContentConfig(
            temperature=1.0,
            top_p=1.0,
            max_output_tokens=10000,
            response_mime_type="application/json",
            response_schema=response_schema_for_list,
            safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
            ]
        )

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=contents,
            config=config
        )

        if hasattr(response, 'text') and response.text:
            return response.text, ""
        
        return "", "AI response was empty or blocked."

    except Exception as e:
        error_msg = f"Gemini API error: {type(e).__name__} - {e}"
        logging.error(error_msg)
        # Re-raise the exception to allow tenacity to handle the retry
        raise

def generate_content_sync(prompt: str, model_name: str) -> Tuple[str, str]:
    """
    Calls the Gemini API synchronously for text-only generation.
    Used for generating the clip list from metadata.
    Returns a tuple of (response_text, error_message_string).
    """
    if not client:
        return "", "Genai Client is not initialized."

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        if hasattr(response, 'text') and response.text:
            return response.text, ""
        else:
            # Handle cases where the response might be blocked or empty
            return "", "AI response was empty or blocked."

    except Exception as e:
        error_msg = f"Gemini API error: {type(e).__name__} - {e}"
        logging.error(error_msg)
        return "", error_msg