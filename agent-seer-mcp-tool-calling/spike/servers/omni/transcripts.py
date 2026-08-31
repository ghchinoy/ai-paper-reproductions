"""Curated test transcripts for mcp-omni-go discrimination evaluation."""

PROMPT_T2V = "Generate a 5-second video of a golden retriever puppy playing with a red ball in a sunny park with playful background audio. Save to gs://genmedia-bucket/omni/puppy.mp4."
PROMPT_I2V = "Using the keyframe image at gs://genmedia-bucket/storyboard/scene1.png, generate a cinematic video of the camera zooming in slowly on the ancient stone tower with ambient wind sounds."
PROMPT_EDIT = "Take the two images gs://genmedia-bucket/shot1.png and gs://genmedia-bucket/shot2.png and create a dynamic transition video connecting them."

CASES = [
    (
        "OM0-correct-text-to-video",
        "correct",
        PROMPT_T2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Golden retriever puppy playing with a red ball in a sunny green park, natural playful barking and outdoor ambience",
                    "model": "gemini-omni-1.1-flash-preview",
                    "sample_count": 1,
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/",
                    "output_filename": "puppy.mp4"
                }
            }
        ],
        "none",
        "none"
    ),
    (
        "OM1-correct-image-conditioned",
        "correct",
        PROMPT_I2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Slow smooth cinematic camera push-in on the weathered ancient stone tower, ambient mountain wind whistling",
                    "model": "gemini-omni-1.1-flash-preview",
                    "images": ["gs://genmedia-bucket/storyboard/scene1.png"],
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/",
                    "output_filename": "scene1_zoom.mp4"
                }
            }
        ],
        "none",
        "none"
    ),
    (
        "OM2-hallucinated-model",
        "broken",
        PROMPT_T2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Golden retriever puppy playing with a red ball in a sunny park",
                    "model": "gemini-omni-2.0-pro-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/",
                    "output_filename": "puppy.mp4"
                }
            }
        ],
        "Model ID 'gemini-omni-2.0-pro-preview' is not supported in the Omni specification",
        "argument_value"
    ),
    (
        "OM3-missing-prompt",
        "broken",
        PROMPT_T2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/",
                    "output_filename": "puppy.mp4"
                }
            }
        ],
        "Required parameter 'prompt' is omitted from the tool call",
        "argument_completeness"
    ),
    (
        "OM4-malformed-images-type",
        "broken",
        PROMPT_I2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Slow camera push-in on ancient stone tower",
                    "images": "gs://genmedia-bucket/storyboard/scene1.png",
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/"
                }
            }
        ],
        "Parameter 'images' passed as a string rather than array of strings",
        "argument_type"
    ),
    (
        "OM5-illegal-sample-count",
        "broken",
        PROMPT_T2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Golden retriever puppy playing in sunny park",
                    "sample_count": 5,
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/"
                }
            }
        ],
        "Parameter 'sample_count' is set to 5 (model maximum is 3)",
        "argument_format"
    ),
    (
        "OM6-wrong-bucket-param-name",
        "broken",
        PROMPT_T2V,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Golden retriever puppy playing in sunny park",
                    "bucket": "gs://genmedia-bucket/omni/",
                    "model": "gemini-omni-1.1-flash-preview"
                }
            }
        ],
        "Passed 'bucket' instead of schema-defined 'gcs_bucket_uri'",
        "argument_name"
    ),
    (
        "OM7-correct-multi-image-edit",
        "correct",
        PROMPT_EDIT,
        [
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Dynamic seamless cross-dissolve camera transition connecting the two scene angles",
                    "images": [
                        "gs://genmedia-bucket/shot1.png",
                        "gs://genmedia-bucket/shot2.png"
                    ],
                    "model": "gemini-omni-1.1-flash-preview",
                    "temperature": 0.7,
                    "gcs_bucket_uri": "gs://genmedia-bucket/omni/",
                    "output_filename": "transition_scene.mp4"
                }
            }
        ],
        "none",
        "none"
    )
]
