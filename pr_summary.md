# PR: LM Studio support + PDF resume parser improvements

**Branch:** `main` (HEAD) → `origin/main` (no divergence yet)  
**Uncommitted changes:** 14 files, ~94 lines added / removed

---

## Summary

- **LM Studio** is now a first-class local inference provider alongside Ollama.
- The PDF resume parser's LLM call token budget was increased from `2000` to `8000` (full resumes routinely exceed 2k tokens on verbose local models).
- A robust JSON extraction helper (`_parse_model_json`) guards against truncated/malformed model replies.
- New tests cover LM Studio dispatch, cost calculation, and R4 contract validation.

---

## Changes

### Backend — LLM Client & Cost (`backend/analyzer/`)

| File | Change |
|------|--------|
| `llm_client.py` | Added `lmstudio` provider: routes to `_call_openai` with `base_url=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")`. Sets `reasoning_effort="none"` in the extra body (thinking models like Qwen3 otherwise burn their entire budget on reasoning and return empty content). Also added `extra_body` param to `_call_openai`. |
| `llm_cost.py` | Added `"lmstudio"` to `FREE_PROVIDERS` set; updated docstring. |
| `cv_scorer.py` | Added type guards (`isinstance(..., dict)`) in `_flatten_resume` for experience/education/projects/publications loops — safely handles non-dict entries (e.g. malformed schema fields). |

### Backend — Location Handler (`backend/analyzer/location.py`)

- Added regex `_CODE_COUNTRY = re.compile(r"^([A-Za-z]{2})\s+(USA|US|United States)$", re.I)` to split tokens like "Cambridge, MA USA" into `["MA", "USA"]` so each half can be read independently (prevents misreading the state code+country as a city name).

### Backend — Resumes API (`backend/api/routes_resumes.py`)

- Added `_parse_model_json(raw_response)` helper: finds the first balanced `{...}` in the raw model reply using `_first_json_object` from `routes_autofill`, falling back to stripping markdown code fences and parsing the whole response. Raises a clear 422 on invalid JSON.
- Increased PDF parse LLM call's `max_tokens` from `2000` → `8000` (full resumes routinely exceed 2k tokens).

### Frontend — Settings UI (`frontend/src/classic/Settings.jsx`, `frontend/src/screens/Settings.jsx`)

- Added **LM Studio** option to all LLM provider dropdowns (Inference, Completion, Embedding) with description: "Local inference server running LM Studio at `localhost:1234/v1`."
- Shows a conditional hint in the API key field when LM Studio is selected: "No API key required for local inference. Leave blank to use your default LM Studio configuration."

---

## Verification

- **LM Studio:** Start `lmstudio-server --server http://0.0.0.0:1234` → verify `/v1/models` returns the model list.
- **PDF parser:** `python -m pytest backend/tests/test_parse_resume_pdf.py` — full integration test of the PDF → JSON pipeline.
- **Location handler:** `python -m pytest backend/tests/test_location_handler.py::test_state_code_country_split` → assert "Cambridge, MA USA" splits into ["MA", "USA"].

> **Note:** The LM Studio provider uses `reasoning_effort="none"` in the extra body to prevent thinking models (Qwen3, etc.) from consuming their entire token budget on reasoning and returning empty content.
