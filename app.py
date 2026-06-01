import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd
from openai import OpenAI
from rdflib import Graph, Literal, Namespace, RDF, XSD

ROOT = Path(__file__).resolve().parent
for rel in ("extraction/src", "validation/src", "qa/src"):
    candidate = ROOT / rel
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from extraction_pipeline.llm_adapter import extract_structured_order_with_llm
from extraction_pipeline.pipeline import extract_retail_order_to_graph
from qa_service.sparql import ask_fuseki, question_to_sparql
from qa_service.verbalizer import verbalize_query_results
from validation_gate.infer import materialize_inferred_graph
from validation_gate.validator import validate_graph_against_shapes

EX = Namespace("http://example.org/kg/")
DEFAULT_INPUT_PATH = ROOT / "examples" / "unstructured-retail-order.txt"
DEFAULT_QUESTIONS_PATH = ROOT / "examples" / "questions.txt"
DEFAULT_SHAPES_PATH = ROOT / "contracts" / "shapes" / "core.shacl.ttl"
DEFAULT_SAMPLE_TTL_PATH = ROOT / "contracts" / "sample-data" / "sample.ttl"
DEFAULT_ONTOLOGY_PATH = ROOT / "contracts" / "ontology" / "core.ttl"
DEFAULT_CQ_REGISTRY_PATH = ROOT / "contracts" / "competency-questions" / "cq-registry.yaml"

os.environ.setdefault("GRAPH_BACKEND", "rdflib")
os.environ.setdefault("RDFLIB_STORE_DIR", "data/graph-store")

CUSTOM_CSS = """
:root {
    --app-bg: #0b0d10;
    --panel-bg: #141922;
    --panel-soft: #1a2130;
    --text-main: #f5f7fa;
    --text-muted: #9ea7b8;
    --accent: #ff7a1a;
    --accent-soft: #3a2516;
    --border: #2a3347;
}

body, .gradio-container {
    background: radial-gradient(1000px 500px at 10% -20%, #20283a 0%, var(--app-bg) 60%);
    color: var(--text-main);
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}

.hero-card {
    background: linear-gradient(135deg, #121826, #191f2d);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 12px 16px;
    margin-bottom: 10px;
}

.runtime-card {
    border: 1px solid var(--border);
    background: var(--panel-bg);
    border-radius: 12px;
    padding: 8px 12px;
}

.step-card {
    border: 1px solid var(--border);
    background: var(--panel-bg);
    border-radius: 12px;
    padding: 8px;
}

.section-label {
    color: var(--text-muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 0 0 4px 0;
}

.chip {
    display: inline-block;
    margin-right: 8px;
    margin-bottom: 6px;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 4px 10px;
    background: var(--panel-soft);
    color: var(--text-main);
    font-size: 12px;
}

.chip.ok {
    border-color: #2f7c55;
    background: #143323;
}

.chip.warn {
    border-color: #7f5f28;
    background: var(--accent-soft);
}

button.primary {
    background: linear-gradient(180deg, #ff8a30, var(--accent)) !important;
    border: 0 !important;
}
"""


def _default_input_text() -> str:
    if DEFAULT_INPUT_PATH.exists():
        return DEFAULT_INPUT_PATH.read_text(encoding="utf-8").strip()
    return ""


def _default_question_text() -> str:
    if DEFAULT_QUESTIONS_PATH.exists():
        first = DEFAULT_QUESTIONS_PATH.read_text(encoding="utf-8").strip().splitlines()
        if first:
            return first[0].strip()
    return "Who are the customers?"


def _load_cq_shortcuts() -> list[tuple[str, str]]:
    if not DEFAULT_CQ_REGISTRY_PATH.exists():
        return []

    content = DEFAULT_CQ_REGISTRY_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    shortcuts: list[tuple[str, str]] = []
    current_id = ""
    current_title = ""
    current_status = ""
    current_question = ""

    def flush_current() -> None:
        if current_id and current_question and current_status.lower() == "active":
            button_label = current_id
            if current_title:
                button_label = f"{current_id}: {current_title}"
            shortcuts.append((button_label, current_question))

    for raw_line in lines:
        line = raw_line.strip()

        id_match = re.match(r"^-\s+id:\s*(.+)$", line)
        if id_match:
            flush_current()
            current_id = id_match.group(1).strip()
            current_title = ""
            current_status = ""
            current_question = ""
            continue

        title_match = re.match(r"^title:\s*(.+)$", line)
        if title_match:
            current_title = title_match.group(1).strip().strip('"')
            continue

        question_match = re.match(r"^question:\s*\"(.+)\"$", line)
        if question_match and current_id:
            current_question = question_match.group(1).strip()
            continue

        status_match = re.match(r"^status:\s*(.+)$", line)
        if status_match and current_id:
            current_status = status_match.group(1).strip().strip('"')

    flush_current()

    return shortcuts


def set_question_text(question: str) -> str:
    return question


def set_question_from_label(label: str, shortcuts: list[tuple[str, str]]) -> str:
    for shortcut_label, shortcut_question in shortcuts:
        if shortcut_label == label:
            return shortcut_question
    return ""


def _graph_store_dir() -> Path:
    raw_value = os.getenv("RDFLIB_STORE_DIR", "data/graph-store").strip() or "data/graph-store"
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _graph_counts() -> tuple[int, int, int, int]:
    store = _graph_store_dir()
    raw = len(_load_graph_file(store / "raw.ttl"))
    asserted = len(_load_graph_file(store / "asserted.ttl"))
    inferred = len(_load_graph_file(store / "inferred.ttl"))
    reports = len(_load_graph_file(store / "validation-reports.ttl"))
    return raw, asserted, inferred, reports


def runtime_status_html() -> str:
    backend = os.getenv("GRAPH_BACKEND", "rdflib")
    key_set = bool(os.getenv("OPENAI_API_KEY", "").strip())
    llm_chip = '<span class="chip ok">LLM key: configured</span>' if key_set else '<span class="chip warn">LLM key: missing</span>'
    raw, asserted, inferred, reports = _graph_counts()
    store = _graph_store_dir()
    return (
        '<div class="runtime-card">'
        f'<span class="chip">backend: {backend}</span>'
        f'{llm_chip}'
        f'<span class="chip">raw: {raw}</span>'
        f'<span class="chip">asserted: {asserted}</span>'
        f'<span class="chip">inferred: {inferred}</span>'
        f'<span class="chip">reports: {reports}</span>'
        f'<span class="chip">store: {store}</span>'
        '</div>'
    )


def _load_graph_file(path: Path) -> Graph:
    graph = Graph()
    if path.exists():
        graph.parse(path)
    return graph


def _write_graph_file(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(path), format="turtle")


def _seed_graph_store_with_sample() -> None:
    if not DEFAULT_SAMPLE_TTL_PATH.exists():
        return

    store = _graph_store_dir()
    raw_path = store / "raw.ttl"
    asserted_path = store / "asserted.ttl"
    inferred_path = store / "inferred.ttl"
    reports_path = store / "validation-reports.ttl"

    sample_graph = Graph().parse(DEFAULT_SAMPLE_TTL_PATH)

    raw_graph = Graph()
    for triple in sample_graph:
        raw_graph.add(triple)

    asserted_graph = Graph()
    for triple in sample_graph:
        asserted_graph.add(triple)

    inferred_graph = materialize_inferred_graph(asserted_graph)

    _write_graph_file(raw_graph, raw_path)
    _write_graph_file(asserted_graph, asserted_path)
    _write_graph_file(inferred_graph, inferred_path)

    if not reports_path.exists():
        _write_graph_file(Graph(), reports_path)


def _read_text_or_missing(path: Path) -> str:
    if not path.exists():
        return f"File not found: {path}"
    return path.read_text(encoding="utf-8")


def load_inspection_data() -> tuple[str, str, str, str, str, str, str]:
    store = _graph_store_dir()
    return (
        _read_text_or_missing(store / "raw.ttl"),
        _read_text_or_missing(store / "asserted.ttl"),
        _read_text_or_missing(store / "inferred.ttl"),
        _read_text_or_missing(store / "validation-reports.ttl"),
        _read_text_or_missing(DEFAULT_ONTOLOGY_PATH),
        _read_text_or_missing(DEFAULT_SHAPES_PATH),
        _read_text_or_missing(DEFAULT_SAMPLE_TTL_PATH),
    )


def _llm_only_prompt(text: str) -> str:
    return f"""
You are an information extraction system for retail order notes.
Return ONLY valid JSON with this exact shape:
{{
  "order_id": "ORD-1001",
  "order_date": "YYYY-MM-DD",
  "customer": {{ "id": "CUST-001", "name": "Alice Example" }},
  "store": {{ "id": "STR-AMS-CENTRAL", "name": "Amsterdam Central" }},
  "items": [
    {{ "sku": "SKU-APPLE-001", "product_name": "Gala Apples", "quantity": 2, "unit_price": "1.50" }}
  ]
}}

Rules:
- customer.id must match CUST-[0-9]{{3,}}
- store.id must match STR-[A-Z0-9-]+
- sku must match SKU-[A-Z0-9-]+
- quantity must be integer >= 1
- unit_price must be decimal string with dot
- Return no markdown fences and no explanatory text.

Order note:
{text}
""".strip()


def _extract_llm_only_json(text: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM-only extraction.")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You extract structured retail order data as strict JSON.",
            },
            {
                "role": "user",
                "content": _llm_only_prompt(text=text),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM response did not include content.")
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise RuntimeError("LLM payload must be a JSON object.")
    return payload


def _serialize_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=True)


def _load_graph_from_ttl(ttl: str) -> Graph:
    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    return graph


def _as_jsonld(graph: Graph) -> str:
    try:
        content = graph.serialize(format="json-ld", indent=2)
        return str(content)
    except Exception as exc:
        return f"JSON-LD serialization not available in this environment: {exc}"


def _blank_extraction_state() -> dict[str, Any]:
    return {
        "mode": "",
        "structured_json": "",
        "graph_ttl": "",
        "graph_jsonld": "",
        "conforms": None,
        "report_text": "",
    }


def run_extraction(mode: str, input_text: str, document_id: str) -> tuple[str, str, str, str, dict[str, Any]]:
    text = (input_text or "").strip()
    if not text:
        return "", "", "", "Please provide input text.", _blank_extraction_state()

    state = _blank_extraction_state()
    state["mode"] = mode

    if mode == "LLM only (JSON)":
        try:
            payload = _extract_llm_only_json(text)
        except Exception as exc:
            return "", "", "", f"Extraction failed: {exc}", state

        structured = _serialize_json(payload)
        state["structured_json"] = structured
        return structured, "", "", "LLM-only extraction completed.", state

    prev_strategy = os.getenv("EXTRACTION_STRATEGY", "")
    os.environ["EXTRACTION_STRATEGY"] = "llm"
    try:
        graph = extract_retail_order_to_graph(text=text, document_id=document_id.strip() or "retail-doc-ui-001")
    except Exception as exc:
        return "", "", "", f"Contract-aware extraction failed: {exc}", state
    finally:
        if prev_strategy:
            os.environ["EXTRACTION_STRATEGY"] = prev_strategy
        else:
            os.environ.pop("EXTRACTION_STRATEGY", None)

    ttl = str(graph.serialize(format="turtle"))
    jsonld = _as_jsonld(graph)

    state["graph_ttl"] = ttl
    state["graph_jsonld"] = jsonld
    return "", ttl, jsonld, "Contract-aware extraction completed.", state


def _effective_graph_ttl(state: dict[str, Any], edited_graph_ttl: str) -> str:
    edited = (edited_graph_ttl or "").strip()
    if edited:
        return edited
    return (state or {}).get("graph_ttl", "")


def run_validation(
    mode: str,
    state: dict[str, Any],
    edited_graph_ttl: str,
) -> tuple[str, dict[str, Any]]:
    if mode != "Contract-aware (ontology + SHACL + RDF)":
        return "Validation is only available in contract-aware mode.", state

    graph_ttl = _effective_graph_ttl(state, edited_graph_ttl)
    if not graph_ttl:
        return "No RDF found. Click Extract first.", state

    shapes_path = DEFAULT_SHAPES_PATH
    if not shapes_path.exists():
        return f"Shapes file not found: {shapes_path}", state

    try:
        graph = _load_graph_from_ttl(graph_ttl)
    except Exception as exc:
        return f"RDF parse error. Fix Turtle first.\n\n{exc}", state

    conforms, report_text = validate_graph_against_shapes(graph, shapes_path)

    state["graph_ttl"] = graph_ttl
    state["conforms"] = bool(conforms)
    state["report_text"] = report_text

    verdict = "PASS" if conforms else "FAIL"
    return f"Validation {verdict}.\n\n{report_text}", state


def _append_validation_report_graph(report_text: str, conforms: bool) -> Graph:
    report_graph = Graph()
    report_graph.bind("ex", EX)
    run = EX[f"validation-run-{uuid.uuid4()}"]

    report_graph.add((run, RDF.type, EX.ValidationRun))
    report_graph.add((run, EX.sourceGraph, Literal("urn:graph:raw")))
    report_graph.add((run, EX.targetGraph, Literal("urn:graph:asserted")))
    report_graph.add((run, EX.conforms, Literal(bool(conforms))))
    report_graph.add((run, EX.reportText, Literal(report_text)))
    report_graph.add(
        (
            run,
            EX.validatedAt,
            Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime),
        )
    )
    return report_graph


def save_to_graph_store(mode: str, state: dict[str, Any], edited_graph_ttl: str) -> str:
    if mode != "Contract-aware (ontology + SHACL + RDF)":
        return "Save is only available in contract-aware mode."

    graph_ttl = _effective_graph_ttl(state, edited_graph_ttl)
    if not graph_ttl:
        return "No RDF found. Click Extract first."

    graph_store = _graph_store_dir()
    raw_path = graph_store / "raw.ttl"
    asserted_path = graph_store / "asserted.ttl"
    report_ttl_path = graph_store / "validation-reports.ttl"
    report_txt_path = graph_store / "validation-report.txt"

    existing_raw = _load_graph_file(raw_path)
    try:
        graph = _load_graph_from_ttl(graph_ttl)
    except Exception as exc:
        return f"Save blocked: Turtle RDF could not be parsed.\n\n{exc}"

    existing_orders = set(existing_raw.subjects(RDF.type, EX.Order))
    extracted_orders = set(graph.subjects(RDF.type, EX.Order))
    collisions = sorted(str(uri) for uri in (existing_orders & extracted_orders))
    if collisions:
        preview = "\n".join(collisions[:5])
        return (
            "Save blocked: extracted graph reuses existing Order URI(s).\n"
            "This demo expects new orders to use new order IDs.\n"
            "Change ORDER in input text (for example ORD-2001, ORD-2002, ...) and extract again.\n"
            f"Conflicting URI(s):\n{preview}"
        )

    raw_before = len(existing_raw)
    for triple in graph:
        existing_raw.add(triple)
    raw_after = len(existing_raw)
    _write_graph_file(existing_raw, raw_path)

    lines = [
        f"Merged extracted triples into raw graph: {raw_before} -> {raw_after} triples ({raw_after - raw_before} added)",
        f"Raw graph path: {raw_path}",
    ]

    conforms = (state or {}).get("conforms", None)
    report_text = (state or {}).get("report_text", "")

    if conforms is True:
        existing_asserted = _load_graph_file(asserted_path)
        asserted_before = len(existing_asserted)
        for triple in graph:
            existing_asserted.add(triple)
        asserted_after = len(existing_asserted)
        _write_graph_file(existing_asserted, asserted_path)
        lines.append(
            f"Validation passed, merged into asserted graph: {asserted_before} -> {asserted_after} triples ({asserted_after - asserted_before} added)"
        )
        lines.append(f"Asserted graph path: {asserted_path}")
    elif conforms is False:
        lines.append("Validation failed, asserted graph was not updated.")
    else:
        lines.append("Validation has not been run yet, only raw graph was written.")

    if report_text:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"\n\n---\nSaved at: {timestamp}\n{report_text}\n"
        with report_txt_path.open("a", encoding="utf-8") as report_file:
            report_file.write(entry)

        existing_report_graph = _load_graph_file(report_ttl_path)
        report_graph = _append_validation_report_graph(report_text=report_text, conforms=bool(conforms))
        for triple in report_graph:
            existing_report_graph.add(triple)
        _write_graph_file(existing_report_graph, report_ttl_path)

        lines.append(f"Appended validation report text to {report_txt_path}")
        lines.append(f"Merged validation report graph into {report_ttl_path}")

    return "\n".join(lines)


def reset_startup_state() -> tuple[str, str, str, str, str, str, str, str, dict[str, Any], str, str, str, str, str, str, str, str]:
    _seed_graph_store_with_sample()
    raw_ttl, asserted_ttl, inferred_ttl, reports_ttl, ontology_ttl, shapes_ttl, sample_ttl = (
        load_inspection_data()
    )

    return (
        "Contract-aware (ontology + SHACL + RDF)",
        _default_input_text(),
        "",
        "",
        "",
        "Startup state restored: sample data and inferred graph have been re-seeded.",
        "",
        "",
        _blank_extraction_state(),
        raw_ttl,
        asserted_ttl,
        inferred_ttl,
        reports_ttl,
        ontology_ttl,
        shapes_ttl,
        sample_ttl,
        runtime_status_html(),
    )


def _intent_label(question: str) -> str:
    intent_seed = question_to_sparql(question)
    answer = intent_seed.answer.lower()
    if answer.startswith("i do not understand"):
        return "unknown"
    if "repeat customers" in answer:
        return "repeat_customers"
    if "top products" in answer:
        return "top_products"
    if "order totals" in answer:
        return "order_totals"
    if "product mix" in answer:
        return "product_mix"
    if "daily revenue" in answer:
        return "daily_revenue"
    if "customer query" in answer:
        return "customers"
    return "unknown"


def ask_question(question: str) -> tuple[str, str, pd.DataFrame, str, str]:
    q = (question or "").strip()
    if not q:
        return "unknown", "Please enter a question.", pd.DataFrame(), "", ""

    os.environ["GRAPH_BACKEND"] = "rdflib"

    result = ask_fuseki(q)
    narrative, narrative_source = verbalize_query_results(
        question=q,
        sparql=result.sparql,
        rows=result.rows,
    )

    intent = _intent_label(q)
    source_info = f"narrativeSource={narrative_source}"
    rows_df = pd.DataFrame(result.rows)
    return intent, narrative, rows_df, result.sparql, source_info


def build_ui() -> gr.Blocks:
    raw_ttl, asserted_ttl, inferred_ttl, reports_ttl, ontology_ttl, shapes_ttl, sample_ttl = (
        load_inspection_data()
    )
    shortcuts = _load_cq_shortcuts()
    shortcut_labels = [label for label, _ in shortcuts]

    with gr.Blocks(title="RDF Pipeline Demo") as demo:
        gr.HTML(f"<style>{CUSTOM_CSS}</style>")
        gr.HTML(
            "<div class='hero-card'><h1>RDF Demonstrator</h1>"
            "<p>Guided extraction and QA over semantic contracts.</p></div>"
        )

        with gr.Row():
            runtime_status = gr.HTML(value=runtime_status_html())
            refresh_runtime_btn = gr.Button("Refresh runtime status")

        refresh_runtime_btn.click(runtime_status_html, outputs=[runtime_status])

        with gr.Tab("1) Extraction"):
            gr.Markdown("<p class='section-label'>Step 1 - Configure</p>")
            mode = gr.Radio(
                choices=[
                    "LLM only (JSON)",
                    "Contract-aware (ontology + SHACL + RDF)",
                ],
                value="Contract-aware (ontology + SHACL + RDF)",
                label="Extraction mode",
            )
            input_text = gr.Textbox(
                label="Input text",
                value=_default_input_text(),
                lines=10,
            )
            document_id = gr.Textbox(label="Document ID", value="retail-doc-ui-001")

            gr.Markdown("<p class='section-label'>Step 2 - Run Pipeline</p>")
            with gr.Row():
                extract_btn = gr.Button("Extract", variant="primary")
                validate_btn = gr.Button("Validate (SHACL + business rules)")
                save_btn = gr.Button("Save to local graph store")
                reset_btn = gr.Button("Reset to startup state")

            extract_status = gr.Textbox(label="Status", lines=3)

            gr.Markdown("<p class='section-label'>Step 3 - Review Outputs</p>")
            llm_json_output = gr.Code(label="LLM-only JSON output", language="json")
            ttl_output = gr.Code(label="Contract-aware Turtle RDF output", interactive=True)
            with gr.Accordion("JSON-LD (contract-aware)", open=False):
                jsonld_output = gr.Code(label="JSON-LD", language="json")
            validation_report = gr.Textbox(label="Validation report", lines=14)
            save_status = gr.Textbox(label="Save status", lines=5)
            extraction_state = gr.State(_blank_extraction_state())

            extract_btn.click(
                run_extraction,
                inputs=[mode, input_text, document_id],
                outputs=[llm_json_output, ttl_output, jsonld_output, extract_status, extraction_state],
            )

            validate_btn.click(
                run_validation,
                inputs=[mode, extraction_state, ttl_output],
                outputs=[validation_report, extraction_state],
            )

            save_btn.click(
                save_to_graph_store,
                inputs=[mode, extraction_state, ttl_output],
                outputs=[save_status],
            )

        with gr.Tab("2) QA"):
            with gr.Row():
                shortcut_selector = gr.Dropdown(
                    choices=shortcut_labels,
                    label="Competency question shortcuts",
                    value=shortcut_labels[0] if shortcut_labels else None,
                )
                fill_question_btn = gr.Button("Fill selected CQ")

            question = gr.Textbox(label="Natural language question", value=_default_question_text(), lines=2)
            shortcut_state = gr.State(shortcuts)

            fill_question_btn.click(
                set_question_from_label,
                inputs=[shortcut_selector, shortcut_state],
                outputs=[question],
            )

            ask_btn = gr.Button("Ask", variant="primary")

            intent_output = gr.Textbox(label="Detected intent")
            narrative_output = gr.Textbox(label="Narrative answer", lines=4)
            results_output = gr.Dataframe(
                label="Result rows",
                wrap=True,
                type="pandas",
                interactive=False,
                row_count=(10, "dynamic"),
            )
            with gr.Accordion("Query details", open=False):
                sparql_output = gr.Code(label="Generated SPARQL", language="sql")
                source_output = gr.Textbox(label="Narrative source")

            ask_btn.click(
                ask_question,
                inputs=[question],
                outputs=[intent_output, narrative_output, results_output, sparql_output, source_output],
            )

        with gr.Tab("3) Inspect RDF & Contracts"):
            gr.Markdown(
                "Inspect the current graph-store Turtle files and semantic contracts. "
                "Click refresh after extraction/save operations."
            )
            refresh_btn = gr.Button("Refresh data view")

            with gr.Accordion("Graph store: raw.ttl", open=False):
                raw_view = gr.Code(value=raw_ttl, label="raw.ttl")
            with gr.Accordion("Graph store: asserted.ttl", open=False):
                asserted_view = gr.Code(value=asserted_ttl, label="asserted.ttl")
            with gr.Accordion("Graph store: inferred.ttl", open=False):
                inferred_view = gr.Code(value=inferred_ttl, label="inferred.ttl")
            with gr.Accordion("Graph store: validation-reports.ttl", open=False):
                reports_view = gr.Code(value=reports_ttl, label="validation-reports.ttl")

            with gr.Accordion("Contract: ontology core.ttl", open=False):
                ontology_view = gr.Code(value=ontology_ttl, label="contracts/ontology/core.ttl")
            with gr.Accordion("Contract: SHACL shapes core.shacl.ttl", open=False):
                shapes_view = gr.Code(value=shapes_ttl, label="contracts/shapes/core.shacl.ttl")
            with gr.Accordion("Contract sample-data: sample.ttl", open=False):
                sample_view = gr.Code(value=sample_ttl, label="contracts/sample-data/sample.ttl")

            refresh_btn.click(
                load_inspection_data,
                outputs=[
                    raw_view,
                    asserted_view,
                    inferred_view,
                    reports_view,
                    ontology_view,
                    shapes_view,
                    sample_view,
                ],
            )

            reset_btn.click(
                reset_startup_state,
                outputs=[
                    mode,
                    input_text,
                    llm_json_output,
                    ttl_output,
                    jsonld_output,
                    extract_status,
                    validation_report,
                    save_status,
                    extraction_state,
                    raw_view,
                    asserted_view,
                    inferred_view,
                    reports_view,
                    ontology_view,
                    shapes_view,
                    sample_view,
                    runtime_status,
                ],
            )

    return demo


_seed_graph_store_with_sample()
demo = build_ui()


if __name__ == "__main__":
    demo.launch()
