import json
import os
from typing import Any

from openai import OpenAI


def _prompt_for_structured_extraction(text: str, ontology_text: str) -> str:
    return f"""
You are an information extraction system for retail order notes.
Use the ontology terms to guide extraction semantics.

Ontology (Turtle):
{ontology_text}

Extract the order note below and return ONLY valid JSON with this exact shape:
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


def extract_structured_order_with_llm(text: str, ontology_text: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Configure it in your shell before running extraction."
        )

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
                "content": _prompt_for_structured_extraction(text=text, ontology_text=ontology_text),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM response did not include content")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("LLM payload must be a JSON object")

    return payload
