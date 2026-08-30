"""Discrimination test cases for mcp-lyria-go."""

PROMPT_CLIP = "Generate a 30-second upbeat lofi jazz clip for a study session and save to GCS bucket mybucket with filename study_jazz."
PROMPT_PRO = "Compose a 2-minute cinematic orchestral ambient track without drums or heavy brass, saving to bucket mybucket."

CASES = [
    # (label, kind, prompt, agent_calls, injected_fault, expected_taxonomy)
    ("LY0-correct", "correct", PROMPT_CLIP, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "upbeat lofi jazz with warm piano chords and subtle tape crackle",
            "model_id": "lyria-3-clip-preview",
            "output_gcs_bucket": "mybucket",
            "output_filename": "study_jazz"
        }}
    ], "none", "none"),

    ("LY1-wrong-model-param-name", "broken", PROMPT_CLIP, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "upbeat lofi jazz with warm piano chords and subtle tape crackle",
            "model": "lyria-3-clip-preview",  # Lyria schema expects 'model_id', not 'model'
            "output_gcs_bucket": "mybucket",
            "output_filename": "study_jazz"
        }}
    ], "wrong parameter name 'model' (schema expects 'model_id')", "argument_name"),

    ("LY2-wrong-bucket-param-name", "broken", PROMPT_CLIP, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "upbeat lofi jazz with warm piano chords and subtle tape crackle",
            "model_id": "lyria-3-clip-preview",
            "gcs_bucket_uri": "gs://mybucket/music/",  # Schema expects 'output_gcs_bucket'
            "output_filename": "study_jazz"
        }}
    ], "wrong parameter name 'gcs_bucket_uri' (schema expects 'output_gcs_bucket')", "argument_name"),

    ("LY3-hallucinated-model", "broken", PROMPT_CLIP, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "upbeat lofi jazz with warm piano chords and subtle tape crackle",
            "model_id": "lyria-ultra-composer-001",  # Hallucinated model
            "output_gcs_bucket": "mybucket"
        }}
    ], "model ID does not exist in schema or registry", "argument_value"),

    ("LY4-missing-required-prompt", "broken", PROMPT_CLIP, [
        {"function_name": "lyria_generate_music", "parameters": {
            "model_id": "lyria-3-clip-preview",
            "output_gcs_bucket": "mybucket"
        }}
    ], "missing required 'prompt' parameter", "argument_completeness"),

    ("LY5-correct-full-track", "correct", PROMPT_PRO, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "cinematic orchestral ambient soundtrack with sweeping strings",
            "model_id": "lyria-3-pro-preview",
            "negative_prompt": "drums, heavy brass, percussion",
            "output_gcs_bucket": "mybucket",
            "output_filename": "ambient_orchestra"
        }}
    ], "none", "none"),

    ("LY6-malformed-sample-count", "broken", PROMPT_PRO, [
        {"function_name": "lyria_generate_music", "parameters": {
            "prompt": "cinematic orchestral ambient soundtrack with sweeping strings",
            "model_id": "lyria-3-pro-preview",
            "sample_count": -5,  # Schema specifies minimum: 1
            "output_gcs_bucket": "mybucket"
        }}
    ], "sample_count must be a positive integer (minimum 1)", "argument_format")
]
