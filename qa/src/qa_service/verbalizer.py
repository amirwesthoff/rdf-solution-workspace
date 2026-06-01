import json
import os

from openai import OpenAI


def _fallback_verbalization(question: str, rows: list[dict[str, str]]) -> str:
    if not rows:
        return f"No results were found for: {question}"

    preview = rows[:3]
    preview_text = "; ".join(
        ", ".join(f"{k}={v}" for k, v in row.items()) for row in preview
    )
    if len(rows) > 3:
        return f"Found {len(rows)} results. Examples: {preview_text}."
    return f"Found {len(rows)} results: {preview_text}."


def verbalize_query_results(
    question: str,
    sparql: str,
    rows: list[dict[str, str]],
) -> tuple[str, str]:
    """Return a natural-language explanation of query results.

    Returns a tuple: (narrative, source) where source is 'llm' or 'fallback'.
    """
    if os.getenv("QA_USE_LLM_VERBALIZATION", "true").strip().lower() in {"0", "false", "no"}:
        return _fallback_verbalization(question, rows), "fallback"

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_verbalization(question, rows), "fallback"

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI(api_key=api_key)

    rows_json = json.dumps(rows[:25], ensure_ascii=True)
    prompt = (
        "You are a data analyst assistant.\n"
        "Summarize the query results in clear business language.\n"
        "Do not invent facts beyond the rows provided.\n"
        "If rows are empty, say no results were found.\n\n"
        f"Question: {question}\n"
        f"SPARQL: {sparql}\n"
        f"Rows JSON: {rows_json}\n"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You summarize tabular query results faithfully."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        summary = content.strip()
        if not summary:
            return _fallback_verbalization(question, rows), "fallback"
        return summary, "llm"
    except Exception:
        return _fallback_verbalization(question, rows), "fallback"
