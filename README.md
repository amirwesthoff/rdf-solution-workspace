# RDF Solution Workspace

A single monorepo for four related RDF pipelines:

1. `contracts`: retail ontology, SHACL shapes, namespaces, sample RDF, and competency queries.
2. `extraction`: unstructured retail order text to RDF in the `raw` graph.
3. `validation`: SHACL and rule-based validation before promotion to `asserted`.
4. `qa`: natural language to SPARQL over `asserted` + `inferred` graphs.

## Why Monorepo

This setup is optimized for rapid iteration while keeping strict module boundaries so each module can be split into standalone repositories later.

Current domain: retail orders and basket analytics using fully synthetic data.

## Repository Layout

- `contracts/`
- `extraction/`
- `validation/`
- `qa/`
- `platform/`
- `examples/`
- `docs/`
- `scripts/`

Open `rdf-solution-workspace.code-workspace` in VS Code to load the recommended workspace settings.

## Gradio Demo App (Spaces-friendly)

This repository now includes a Gradio web app entrypoint at `app.py`.

Install app dependencies:

```powershell
pip install -r requirements.txt
```

Run the web app locally:

```powershell
python app.py
```

The app has two tabs:

1. Extraction:
	- `LLM only (JSON)`: returns structured JSON only.
	- `Contract-aware (ontology + SHACL + RDF)`: uses the current default extraction path, outputs Turtle RDF with JSON-LD in an expandable panel, and supports separate `Validate` and `Save` actions.
	- The Turtle output is editable before validation/save, so you can deliberately introduce errors for demonstration.
	- `Reset to startup state` restores the seeded sample + inferred graph baseline.
2. QA:
	- classifies intent, returns narrative answer, and shows result rows.
	- generated SPARQL is shown under an expandable "Query details" section.

3. Inspect RDF & Contracts:
	- shows current graph-store Turtle files (`raw`, `asserted`, `inferred`, `validation-reports`).
	- shows semantic contract files (`contracts/ontology/core.ttl`, `contracts/shapes/core.shacl.ttl`, `contracts/sample-data/sample.ttl`).
	- includes a refresh button to reload current on-disk content.

Notes:

- The Gradio app enforces `GRAPH_BACKEND=rdflib` (Spaces-friendly default).
- On startup, the app seeds local graph-store with full sample data plus inferred graph.
- Save action merges extracted triples into local graph-store files (`data/graph-store`) instead of overwriting.

## Deploy to Hugging Face Spaces

For a complete GitHub + HF Spaces publishing flow, see:

- [docs/publish-github-hf-spaces.md](docs/publish-github-hf-spaces.md)

Note: use `hf auth login` (the older `huggingface-cli login` is deprecated).

Use these settings when creating a new Space:

1. SDK: `Gradio`
2. App file: `app.py`
3. Python version: `3.11` (recommended)
4. Dependencies file: `requirements.txt`

Set Space secrets (Settings -> Variables and secrets):

- `OPENAI_API_KEY` (required for LLM-only extraction and LLM verbalization)

Optional Space variables:

- `OPENAI_MODEL=gpt-4.1-mini`
- `QA_USE_LLM_VERBALIZATION=true`
- `RDFLIB_STORE_DIR=data/graph-store`

Behavior in Spaces:

- The UI runs in `rdflib` mode (no Fuseki required).
- Extraction `Save` writes files under local space storage (`data/graph-store`).
- LLM-only extraction fails gracefully with a clear error if `OPENAI_API_KEY` is not set.
- QA verbalization falls back automatically when key/model access is unavailable.

If you duplicate the Space, remember to re-add your own `OPENAI_API_KEY` in that Space.

## Quickstart (Windows PowerShell)

LLM-assisted extraction is the default mode.
rdflib on-disk graph persistence is the default backend mode.

1. Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install package dependencies:

```powershell
pip install -e .\extraction -e .\validation -e .\qa
```

Set your OpenAI API key in the same terminal session before running extraction workflows:

```powershell
$env:OPENAI_API_KEY = "<PASTE_YOUR_KEY_HERE>"
```

Optional persistent setup for future terminals:

```powershell
setx OPENAI_API_KEY "<PASTE_YOUR_KEY_HERE>"
```

Optional knobs:

```powershell
$env:OPENAI_MODEL = "gpt-4.1-mini"
$env:EXTRACTION_STRATEGY = "llm"   # default; use "deterministic" for fallback
$env:GRAPH_BACKEND = "rdflib"      # default; use "fuseki" for SPARQL endpoint mode
$env:RDFLIB_STORE_DIR = "data/graph-store"
$env:ONTOLOGY_PATH = "contracts/ontology/core.ttl"
$env:QA_USE_LLM_VERBALIZATION = "true"   # default; set to "false" to disable LLM verbalization
```

3. Optional: start Fuseki if you want endpoint mode:

```powershell
docker compose up -d
```

4. Load sample data:

```powershell
.\scripts\load-sample.ps1
```

This now uploads sample data and prints triple counts for key named graphs.
By default this writes to on-disk rdflib files in `data/graph-store/`.

For Fuseki mode:

```powershell
$env:GRAPH_BACKEND = "fuseki"
.\scripts\load-sample.ps1
```

Or run one-step LLM-assisted extraction from unstructured text into the raw graph:

```powershell
.\.venv\Scripts\python.exe -m extraction_pipeline.cli --input examples/unstructured-retail-order.txt
```

5. Validate and promote from raw to asserted:

```powershell
.\.venv\Scripts\python.exe -m validation_gate.cli
```

6. Verify graph counts any time:

```powershell
.\scripts\verify-graph.ps1
```

Use Fuseki backend explicitly (optional):

```powershell
$env:GRAPH_BACKEND = "fuseki"
.\scripts\verify-graph.ps1
```

Reset on-disk rdflib graph files between demos/tests:

```powershell
.\scripts\reset-graph-store.ps1
```

7. Materialize inferred graph from asserted graph:

```powershell
.\.venv\Scripts\python.exe -m validation_gate.infer
```

8. Run tests:

```powershell
pytest
```

Run the Fuseki-backed end-to-end integration test:

```powershell
pytest -m integration
```

9. Launch QA API:

```powershell
uvicorn qa_service.main:app --app-dir .\qa\src --reload
```

10. Ask a live question (in another terminal):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask -ContentType "application/json" -Body '{"question":"Who are the customers?"}'
```

One-command rdflib demo pipeline:

```powershell
.\scripts\demo.ps1 -ResetFirst
```

Run from unstructured text instead of sample Turtle:

```powershell
.\scripts\demo.ps1 -ResetFirst -InputTextPath .\examples\unstructured-retail-order.txt
```

Run full demo and start API at the end:

```powershell
.\scripts\demo.ps1 -ResetFirst -LaunchApi
```

One-command Fuseki demo pipeline:

```powershell
.\scripts\demo-fuseki.ps1 -ResetFirst
```

Fuseki demo from unstructured text:

```powershell
.\scripts\demo-fuseki.ps1 -ResetFirst -InputTextPath .\examples\unstructured-retail-order.txt
```

Fuseki demo plus API launch:

```powershell
.\scripts\demo-fuseki.ps1 -ResetFirst -LaunchApi
```

The `/ask` response now includes `narrative` (human-readable summary) and
`narrativeSource` (`llm` or `fallback`).
LLM verbalization is enabled by default when `OPENAI_API_KEY` is available in the
same process running the API server.

## Unstructured Extraction Demo

Use [examples/unstructured-retail-order.txt](examples/unstructured-retail-order.txt) as the source note format for extraction.
The extraction pipeline now uses the ontology text to ground LLM extraction prompts and produces RDF aligned to the retail contract.

## Named Graph Conventions

- `urn:graph:raw`
- `urn:graph:asserted`
- `urn:graph:inferred`
- `urn:graph:validation-reports`
- `urn:graph:provenance`

## Next Steps

- Add SHACL SPARQL constraints for `lineTotal = lineQuantity * lineUnitPrice` and order-level rollups.
- Add provenance triples that record extraction strategy (`llm` or `deterministic`) for each ingest run.
- Add CI workflow stage to run `pytest -m integration` with a Fuseki service container.
