"""Discrimination test cases for mcp-veo-go."""

PROMPT_A = ("Generate a 16:9 cinematic video of a slow pan across a calm "
            "mountain lake at sunrise, with audio. Save it to "
            "gs://mybucket/out/.")

PROMPT_B = ("I already have an image at gs://mybucket/in.png. Animate it into "
            "a short video and save it to gs://mybucket/out/.")

CASES = [
    # (label, kind, prompt, agent_calls, injected_fault, expected_taxonomy)
    ("A0-correct", "correct", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "none", "none"),

    ("A1-wrong-model-value", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-2.0-generate-001",  # does NOT support generate_audio
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "veo-2.0 model rejects generate_audio=true", "argument_value"),

    ("A2-illegal-enum", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "21:9",  # not a supported aspect ratio
            "generate_audio": True, "bucket": "gs://mybucket/out/"}}],
     "aspect_ratio 21:9 not supported", "argument_format"),

    ("A3-hallucinated-model", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.5-ultra-generate-001",  # does not exist
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "model ID does not exist in spec", "argument_value"),

    ("A4-missing-required", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {  # 'prompt' is REQUIRED
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "missing required 'prompt'", "argument_completeness"),

    ("A5-wrong-tool", "broken", PROMPT_A, [
        {"function_name": "veo_i2v", "parameters": {  # no image was provided
            "image_uri": "gs://mybucket/nonexistent.png",
            "bucket": "gs://mybucket/out/"}}],
     "used i2v with no source image (should be t2v)", "selection"),

    ("A6-wrong-param-names", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "ratio": "16:9",            # should be aspect_ratio
            "gcs_bucket": "gs://mybucket/out/"}}],  # should be bucket
     "invalid parameter names ratio/gcs_bucket", "argument_name"),

    ("B0-correct", "correct", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {
            "image_uri": "gs://mybucket/in.png",
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "none", "none"),

    ("B1-wrong-tool", "broken", PROMPT_B, [
        {"function_name": "veo_t2v", "parameters": {  # ignores the image
            "prompt": "animate the image into a short video",
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "used t2v, ignoring the provided image (should be i2v)", "selection"),

    ("B2-missing-required-image", "broken", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {  # image_uri REQUIRED
            "prompt": "animate it", "bucket": "gs://mybucket/out/"}}],
     "missing required image_uri", "argument_completeness"),

    ("B3-malformed-uri", "broken", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {
            "image_uri": "in.png",  # must be a gs:// URI
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "image_uri not a gs:// URI", "argument_format"),
]
