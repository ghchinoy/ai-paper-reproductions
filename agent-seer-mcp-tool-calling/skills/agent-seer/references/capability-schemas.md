# Capability Matrix Specification & Overlay Guide

## Why Capability Overlays are Necessary

Standard Model Context Protocol (MCP) JSON schemas define the syntactic contract for tool parameters. However, in generative media, machine learning, and multi-model tools:
- The JSON schema is shared across multiple backend models.
- Specific parameter combinations (e.g. `generate_audio: true` on `veo-2.0`, or `image_size: "4K"` on `gemini-2.5-flash-image`) are fatal runtime errors on specific models, yet syntactically valid in the generic JSON schema.

This phenomenon is termed **Schema-Blindness**.

## Capability Matrix Format

Capability matrices are structured JSON dictionaries mapping model IDs to their exact operational boundaries:

```json
{
  "model_id_1": {
    "SupportedAspectRatios": ["16:9", "9:16", "1:1"],
    "SupportedDurations": [5, 8],
    "SupportsGenerateAudio": false,
    "SupportedImageSizes": ["1K", "2K"]
  },
  "model_id_2": {
    "SupportedAspectRatios": ["16:9", "9:16"],
    "SupportedDurations": [5, 10],
    "SupportsGenerateAudio": true,
    "SupportedImageSizes": ["1K", "2K", "4K"]
  }
}
```

## How Agent Seer Uses Capabilities

1. **Deterministic Linter (`agent_seer.linter`):**
   - Statically validates that model arguments and associated parameters (such as `generate_audio`, `image_size`, and `aspect_ratio`) strictly match the declared capabilities of the chosen model in $<0.01\text{ ms}$.
2. **LLM-as-a-Judge (`agent_seer.judge`):**
   - Appends the matrix to the tool specifications prompt, ensuring the evaluator penalizes capability violations that are invisible to raw JSON schemas.
