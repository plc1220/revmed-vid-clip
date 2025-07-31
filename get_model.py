import google.generativeai as genai
import os

# Configure with your API key
# gemini_api_key = os.environ.get("GEMINI_API_KEY") # Or however you get your key
DEFAULT_GEMINI_API_KEY = "AIzaSyBkuO_FfMRh1mvcy6XGKTbxPsR9mqCracg" # Default key

_genai_configured_once = False

def configure_genai_with_key(api_key_to_use: str):
    """Configures the genai module with the provided API key."""
    global _genai_configured_once
    if not api_key_to_use:
        print("No API key provided to configure_genai_with_key. Genai not configured by this function.")
        return

    try:
        genai.configure(api_key=api_key_to_use)
        print(f"Genai configured successfully with provided API key (ending with ...{api_key_to_use[-4:]}).")
        
        # Optionally, list models upon successful configuration by this function
        # print("Models available after dynamic configuration:")
        # for m in genai.list_models():
        #     if 'generateContent' in m.supported_generation_methods:
        #         print(f"- {m.name}")
        _genai_configured_once = True
    except Exception as e:
        print(f"Error configuring Genai with provided API key: {e}")

# Initial configuration using the default key, if not already configured by app.py
# This allows the script to be runnable standalone for testing or if app.py doesn't call the new function.
if not _genai_configured_once and DEFAULT_GEMINI_API_KEY:
    try:
        genai.configure(api_key=DEFAULT_GEMINI_API_KEY)
        _genai_configured_once = True
        print(f"Genai configured with DEFAULT_GEMINI_API_KEY (ending with ...{DEFAULT_GEMINI_API_KEY[-4:]}) on import.")
        print("Available models that support 'generateContent' (on import):")
    except Exception as e:
        print(f"Error configuring Genai with DEFAULT_GEMINI_API_KEY on import: {e}")
else:
    if not DEFAULT_GEMINI_API_KEY:
        print("DEFAULT_GEMINI_API_KEY is not set in get_model.py. Genai not configured on import.")

# The following model listing will run if genai was configured by any means
if _genai_configured_once:
    print("Listing models (this runs if genai was configured by any means):")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name} (Display Name: {m.display_name}, Description: {m.description[:60]}...)")
    print("\nFull list of models:")
    for m in genai.list_models():
        print(f"- {m.name} (Supported Methods: {m.supported_generation_methods})")

# else: # This else corresponds to the initial `if gemini_api_key:` which is now part of the logic above
#     print("GEMINI_API_KEY not found initially.") # Or some other message if default key is also missing