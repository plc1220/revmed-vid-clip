import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Tuple

# --- Gemini Configuration ---

_genai_configured = False

def configure_genai(api_key: str) -> Tuple[bool, str]:
    """Configures the genai module with the provided API key."""
    global _genai_configured
    if not api_key:
        return False, "No API key provided to configure_genai."
    
    try:
        genai.configure(api_key=api_key)
        _genai_configured = True
        print(f"Genai configured successfully with provided API key.")
        return True, ""
    except Exception as e:
        _genai_configured = False
        print(f"Error configuring Genai: {e}")
        return False, f"Error configuring Genai: {e}"

# --- API Call Logic ---

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3)
)
async def generate_content_async(prompt: str, gcs_video_uri: str, model_name: str) -> Tuple[str, str]:
    """
    Calls the Gemini API asynchronously to generate content based on a video and prompt.
    Returns a tuple of (response_text, error_message_string).
    """
    global _genai_configured
    if not _genai_configured:
        return "", "Genai is not configured. Please call configure_genai first."

    try:
        model = genai.GenerativeModel(model_name=model_name)
        
        # The content for the API call
        contents = [gcs_video_uri, prompt]
        
        # Generation settings
        generation_config = genai.types.GenerationConfig(
            temperature=1.0, 
            top_p=1.0, 
            max_output_tokens=8192
        )
        
        # Safety settings to avoid blocking
        safety_settings = [
            {"category": genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
            {"category": genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE},
        ]

        response = await model.generate_content_async(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        full_response_text = ""
        if hasattr(response, 'text') and response.text:
            full_response_text = response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                 if hasattr(part, 'text'):
                    full_response_text += part.text
        
        if not full_response_text and response.prompt_feedback:
            block_reason = getattr(response.prompt_feedback, 'block_reason', None)
            if block_reason:
                reason_message = f"Content generation blocked. Reason: {block_reason.name}"
                return "", reason_message

        return full_response_text, ""

    except Exception as e:
        error_msg = f"Gemini API error: {type(e).__name__} - {e}"
        print(error_msg)
        # Re-raise the exception to allow tenacity to handle the retry
        raise

def generate_content_sync(prompt: str, model_name: str) -> Tuple[str, str]:
    """
    Calls the Gemini API synchronously for text-only generation.
    Used for generating the clip list from metadata.
    Returns a tuple of (response_text, error_message_string).
    """
    global _genai_configured
    if not _genai_configured:
        return "", "Genai is not configured. Please call configure_genai first."

    try:
        model = genai.GenerativeModel(model_name=model_name)
        response = model.generate_content(prompt)
        
        if hasattr(response, 'text') and response.text:
            return response.text, ""
        else:
            # Handle cases where the response might be blocked or empty
            return "", "AI response was empty or blocked."

    except Exception as e:
        error_msg = f"Gemini API error: {type(e).__name__} - {e}"
        print(error_msg)
        return "", error_msg