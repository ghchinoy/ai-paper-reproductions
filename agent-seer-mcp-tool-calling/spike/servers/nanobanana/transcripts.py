"""Discrimination test cases for mcp-nanobanana-go."""

PROMPT_T2I = "Generate a vibrant, high-resolution 16:9 landscape image of a futuristic solar city in 2K, saving to gs://mybucket/out/."
PROMPT_I2I = "Take the existing image at gs://mybucket/source.png and edit it to look like it is snowing at night."

CASES = [
    # (label, kind, prompt, agent_calls, injected_fault, expected_taxonomy)
    ("NB0-correct", "correct", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
            "model": "gemini-3.1-flash-image",
            "aspect_ratio": "16:9",
            "image_size": "2K",
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "none", "none"),

    ("NB1-illegal-size-on-2.5", "broken", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
            "model": "gemini-2.5-flash-image",  # Does NOT support image_size
            "aspect_ratio": "16:9",
            "image_size": "4K",
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "gemini-2.5-flash-image does not support image_size parameter", "argument_value"),

    ("NB2-illegal-aspect-ratio", "broken", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
            "model": "gemini-2.5-flash-image",
            "aspect_ratio": "1:8",  # Extreme ratio only supported on Gemini 3+
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "aspect_ratio 1:8 is not supported on gemini-2.5-flash-image", "argument_format"),

    ("NB3-hallucinated-model", "broken", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
            "model": "imagen-3.5-ultra-banana",  # Hallucinated model ID
            "aspect_ratio": "16:9",
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "model ID does not exist in schema or registry", "argument_value"),

    ("NB4-missing-required-prompt", "broken", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "model": "gemini-3.1-flash-image",
            "aspect_ratio": "16:9",
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "missing required 'prompt' parameter", "argument_completeness"),

    ("NB5-wrong-param-names", "broken", PROMPT_T2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
            "model": "gemini-3.1-flash-image",
            "ratio": "16:9",  # Should be aspect_ratio
            "bucket": "gs://mybucket/out/"  # Should be gcs_bucket_uri
        }}
    ], "wrong parameter names ratio/bucket (schema expects aspect_ratio, gcs_bucket_uri)", "argument_name"),

    ("NB6-correct-image-to-image", "correct", PROMPT_I2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "modify the scene to add heavy falling snow and night lighting",
            "model": "gemini-3-pro-image",
            "images": ["gs://mybucket/source.png"],
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "none", "none"),

    ("NB7-malformed-images-type", "broken", PROMPT_I2I, [
        {"function_name": "nanobanana_image_generation", "parameters": {
            "prompt": "modify the scene to add heavy falling snow and night lighting",
            "model": "gemini-3-pro-image",
            "images": "gs://mybucket/source.png",  # Schema requires array of strings, not a bare string
            "gcs_bucket_uri": "gs://mybucket/out/"
        }}
    ], "images parameter must be an array of string URIs/paths, not string", "argument_type")
]
