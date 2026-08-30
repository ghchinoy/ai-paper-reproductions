# Agent Seer spike — mcp-veo-go orchestration-correctness judge

Throwaway validation spike (arXiv 2608.26133, Option A). Result + go/no-go:
`../spike-result.md`.

## Layout
- `gemini_client.py` — Vertex `generateContent` REST client (urllib + gcloud token; no pip deps).
- `prompts.py` — paper prompts. Stages 1–4 verbatim (Appendix D); TC/Coherence judge prompts reconstructed from Tables 18/19 + cascading footnote. Provenance in the module docstring.
- `scoring.py` — TC/Coherence aggregation per §4 / Appendix E.
- `judge.py` — applies the judge prompts + aggregation.
- `agent_seer_spike.py` — pipeline: ingest spec → Stage 1 interpret → Stage 2 scenarios → Stage 3 mock outputs (seeded).
- `discrimination_test.py` — the actual proof: correct vs deliberately-broken transcripts on veo's real schema.
- `seed_outputs.json` — real mcp-veo-go response shape used to raise Stage-3 grounding above `low`.
- `artifacts/` — all inputs/outputs: `veo_tools_list.json` (real spec), stage1/2/3 outputs, `discrimination_results.json`, `discrimination_enriched.json`, `veo_model_capabilities.json`.

## Reproduce
Needs `gcloud` ADC (project `ghchinoy-genai-sa`), `python3`, `go` (only to re-pull the spec).
```
cd spike
python3 agent_seer_spike.py            # regenerate stages 1-3
python3 discrimination_test.py --second-judge   # run the discrimination proof
```
Re-pull the spec (already saved in artifacts/):
```
cd .../mcp-genmedia/mcp-genmedia-go/mcp-veo-go && go build -o /tmp/mcp-veo-go .
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"s","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | /tmp/mcp-veo-go
```
