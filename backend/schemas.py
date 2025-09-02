from pydantic import BaseModel, Field
from typing import List, Optional

class TrailerClipMetadata(BaseModel):
    """Pydantic model for a single trailer clip's metadata."""
    source_filename: str = Field(description="The filename of the video clip being analyzed.")
    timestamp_start_end: str = Field(description="Precise in and out points for the clip (HH:MM:SS - HH:MM:SS) relative to the start of the provided video file.")
    editor_note_clip_rationale: str = Field(description="Your rationale for selecting this clip. Why is it trailer-worthy? (Max 30 words)")
    brief_scene_description: str = Field(description="Concisely summarize the core action, setting, and characters. (Max 25 words)")
    key_dialogue_snippet: str = Field(description="Most potent intriguing, or revealing line(s) of dialogue (verbatim, max 2 lines). If none, state 'None' or 'Action/Visual Only.'")
    dominant_emotional_tone_impact: str = Field(description="Primary feeling(s) or impact evoked. (Max 5 keywords, comma-separated)")
    key_visual_elements_cinematography: str = Field(description="Striking visuals, camera work, lighting, etc. (Max 5 keywords/phrases, comma-separated)")
    characters_in_focus_objective_emotion: str = Field(description="Who is central? Their objective or strong emotion? (Max 15 words)")
    plot_relevance_significance: str = Field(description="Why is this moment important for the narrative or trailer? (Max 20 words)")
    trailer_potential_category: str = Field(description="How could this clip be used? (Choose one or two from list, comma-separated) Options: Hook/Opening, Character Introduction, Inciting Incident, Conflict Build-up, Rising Action, Tension/Suspense Peak, Emotional Beat, Action Sequence Highlight, Twist/Reveal Tease, Climax Tease, Resolution Glimpse, Cliffhanger/Question, Thematic Montage Element")
    pacing_suggestion_for_clip: str = Field(description="How should this clip feel in a trailer sequence? (Choose one from list) Options: Rapid Cut, Medium Pace, Slow Burn/Held Shot, Builds Intensity, Sudden Impact")
    music_sound_cue_idea: Optional[str] = Field(default=None, description="Optional. Sound to amplify the moment. (Max 10 words)")

class UploadURLRequest(BaseModel):
    file_name: str
    content_type: str
    gcs_bucket: str
    workspace: str

class UploadURLResponse(BaseModel):
    upload_url: str
    gcs_blob_name: str

class FaceClipGenerationRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_video_uri: str
    gcs_cast_photo_uris: list[str]
    output_gcs_prefix: str

class SplitRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_blob_name: str
    segment_duration: int  # in seconds


class MetadataRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    gcs_video_uris: list[str]
    prompt_template: str
    ai_model_name: str
    gcs_output_prefix: str
    language: Optional[str] = None


class ClipGenerationRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    metadata_blob_names: list[str]  # GCS paths to the metadata files
    output_gcs_prefix: str


class JoinRequest(BaseModel):
    workspace: str
    gcs_bucket: str
    clip_blob_names: list[str]
    output_gcs_prefix: str


class GCSDeleteRequest(BaseModel):
    gcs_bucket: str
    blob_name: str


class GCSBatchDeleteRequest(BaseModel):
    gcs_bucket: str
    blob_names: List[str]


class UploadResponse(BaseModel):
    gcs_bucket: str
    gcs_blob_name: str
    workspace: str

class SignedURLRequest(BaseModel):
    bucket_name: str
    blob_name: str

class SignedURLResponse(BaseModel):
    signed_url: str