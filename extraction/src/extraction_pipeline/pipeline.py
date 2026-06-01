import re
from pathlib import Path
import os
from decimal import Decimal

from rdflib import Graph, Literal, Namespace, RDF, XSD

EX = Namespace("http://example.org/kg/")

ORDER_ID_PATTERN = re.compile(r"^ORDER:\s*(ORD-[0-9]{4,})$", re.MULTILINE)
DATE_PATTERN = re.compile(r"^DATE:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})$", re.MULTILINE)
CUSTOMER_PATTERN = re.compile(
    r"^CUSTOMER:\s*(CUST-[0-9]{3,})\s*\|\s*(.+)$", re.MULTILINE
)
STORE_PATTERN = re.compile(r"^STORE:\s*(STR-[A-Z0-9-]+)\s*\|\s*(.+)$", re.MULTILINE)
ITEM_PATTERN = re.compile(
    r"^ITEM:\s*(SKU-[A-Z0-9-]+)\s*\|\s*(.+?)\s*\|\s*qty=([0-9]+)\s*\|\s*unit=([0-9]+(?:\.[0-9]{1,2})?)$",
    re.MULTILINE,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _require_match(pattern: re.Pattern[str], text: str, field_name: str) -> str:
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Missing or invalid {field_name} in retail order text")
    return match.group(1).strip()


def _parse_retail_order_text_deterministic(text: str) -> dict[str, object]:
    order_id = _require_match(ORDER_ID_PATTERN, text, "order id")
    order_date = _require_match(DATE_PATTERN, text, "order date")

    customer_match = CUSTOMER_PATTERN.search(text)
    if not customer_match:
        raise ValueError("Missing or invalid customer line")
    customer_id = customer_match.group(1).strip()
    customer_name = customer_match.group(2).strip()

    store_match = STORE_PATTERN.search(text)
    if not store_match:
        raise ValueError("Missing or invalid store line")
    store_id = store_match.group(1).strip()
    store_name = store_match.group(2).strip()

    item_matches = list(ITEM_PATTERN.finditer(text))
    if not item_matches:
        raise ValueError("Retail order text must contain at least one ITEM line")

    items: list[dict[str, object]] = []
    for item in item_matches:
        items.append(
            {
                "sku": item.group(1).strip(),
                "product_name": item.group(2).strip(),
                "quantity": int(item.group(3).strip()),
                "unit_price": item.group(4).strip(),
            }
        )

    return {
        "order_id": order_id,
        "order_date": order_date,
        "customer": {
            "id": customer_id,
            "name": customer_name,
        },
        "store": {
            "id": store_id,
            "name": store_name,
        },
        "items": items,
    }


def _validate_structured_order_payload(payload: dict[str, object]) -> None:
    required_top = ["order_id", "order_date", "customer", "store", "items"]
    missing = [key for key in required_top if key not in payload]
    if missing:
        raise ValueError(f"Missing keys in extracted payload: {', '.join(missing)}")

    customer = payload["customer"]
    store = payload["store"]
    items = payload["items"]
    if not isinstance(customer, dict) or not isinstance(store, dict) or not isinstance(items, list):
        raise ValueError("Extracted payload has invalid customer/store/items structure")

    customer_id = str(customer.get("id", "")).strip()
    store_id = str(store.get("id", "")).strip()
    if not re.match(r"^CUST-[0-9]{3,}$", customer_id):
        raise ValueError(f"Invalid customer id in extracted payload: {customer_id}")
    if not re.match(r"^STR-[A-Z0-9-]+$", store_id):
        raise ValueError(f"Invalid store id in extracted payload: {store_id}")

    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item #{idx} is not an object")
        sku = str(item.get("sku", "")).strip()
        quantity_raw = item.get("quantity")
        unit_price_raw = item.get("unit_price")
        if not re.match(r"^SKU-[A-Z0-9-]+$", sku):
            raise ValueError(f"Invalid SKU for item #{idx}: {sku}")
        try:
            quantity = int(quantity_raw)
            unit_price = Decimal(str(unit_price_raw))
        except Exception as exc:
            raise ValueError(f"Invalid quantity or unit_price for item #{idx}") from exc
        if quantity < 1:
            raise ValueError(f"Quantity must be >= 1 for item #{idx}")
        if unit_price < 0:
            raise ValueError(f"Unit price must be >= 0 for item #{idx}")


def _build_graph_from_structured_order(
    payload: dict[str, object],
    document_id: str,
) -> Graph:
    _validate_structured_order_payload(payload)

    order_id = str(payload["order_id"])
    order_date = str(payload["order_date"])
    customer = payload["customer"]
    store = payload["store"]
    items = payload["items"]

    g = Graph()
    g.bind("ex", EX)

    doc = EX[_slug(document_id)]
    g.add((doc, RDF.type, EX.RetailDocument))

    customer_id = str(customer["id"])
    customer_name = str(customer["name"])
    customer_ref = EX[f"customer-{_slug(customer_id)}"]
    g.add((customer_ref, RDF.type, EX.Customer))
    g.add((customer_ref, EX.customerId, Literal(customer_id)))
    g.add((customer_ref, EX.customerName, Literal(customer_name)))

    store_id = str(store["id"])
    store_name = str(store["name"])
    store_ref = EX[f"store-{_slug(store_id)}"]
    g.add((store_ref, RDF.type, EX.Store))
    g.add((store_ref, EX.storeId, Literal(store_id)))
    g.add((store_ref, EX.storeName, Literal(store_name)))

    order_ref = EX[f"order-{_slug(order_id)}"]
    g.add((order_ref, RDF.type, EX.Order))
    g.add((order_ref, EX.orderId, Literal(order_id)))
    g.add((order_ref, EX.orderDate, Literal(order_date, datatype=XSD.date)))
    g.add((order_ref, EX.placedBy, customer_ref))
    g.add((order_ref, EX.soldAtStore, store_ref))
    g.add((order_ref, EX.extractedFromDocument, doc))

    order_total = Decimal("0")
    for index, item in enumerate(items, start=1):
        sku = str(item["sku"])
        product_name = str(item["product_name"])
        quantity = int(item["quantity"])
        unit_price = Decimal(str(item["unit_price"]))
        line_total = unit_price * quantity
        order_total += line_total

        product = EX[f"product-{_slug(sku)}"]
        g.add((product, RDF.type, EX.Product))
        g.add((product, EX.sku, Literal(sku)))
        g.add((product, EX.productName, Literal(product_name)))
        g.add((product, EX.listPrice, Literal(str(unit_price), datatype=XSD.decimal)))

        line = EX[f"orderline-{_slug(order_id)}-{index}"]
        g.add((line, RDF.type, EX.OrderLine))
        g.add((line, EX.lineProduct, product))
        g.add((line, EX.lineQuantity, Literal(quantity, datatype=XSD.integer)))
        g.add((line, EX.lineUnitPrice, Literal(str(unit_price), datatype=XSD.decimal)))
        g.add((line, EX.lineTotal, Literal(str(line_total), datatype=XSD.decimal)))
        g.add((order_ref, EX.hasLine, line))

    g.add((order_ref, EX.totalAmount, Literal(str(order_total), datatype=XSD.decimal)))
    return g


def extract_retail_order_to_graph(text: str, document_id: str = "retail-doc-001") -> Graph:
    """Extract a retail order from unstructured text and materialize RDF.

    Expected text format example:
      ORDER: ORD-1001
      DATE: 2026-05-30
      CUSTOMER: CUST-001 | Alice Example
      STORE: STR-AMS-CENTRAL | Amsterdam Central
      ITEM: SKU-APPLE-001 | Gala Apples | qty=2 | unit=1.50
    """
    strategy = os.getenv("EXTRACTION_STRATEGY", "llm").strip().lower()

    if strategy == "llm":
        ontology_path = Path(os.getenv("ONTOLOGY_PATH", "contracts/ontology/core.ttl"))
        if not ontology_path.exists():
            raise FileNotFoundError(f"Ontology file not found for LLM extraction: {ontology_path}")
        ontology_text = ontology_path.read_text(encoding="utf-8")

        from .llm_adapter import extract_structured_order_with_llm

        payload = extract_structured_order_with_llm(text=text, ontology_text=ontology_text)
        return _build_graph_from_structured_order(payload, document_id=document_id)

    if strategy == "deterministic":
        payload = _parse_retail_order_text_deterministic(text)
        return _build_graph_from_structured_order(payload, document_id=document_id)

    raise ValueError(
        "Unsupported EXTRACTION_STRATEGY. Use 'llm' (default) or 'deterministic'."
    )


def extract_people_to_graph(text: str, document_id: str = "retail-doc-001") -> Graph:
    """Backward-compatible alias kept for earlier scripts/tests."""
    return extract_retail_order_to_graph(text, document_id=document_id)
