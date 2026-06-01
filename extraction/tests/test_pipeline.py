import os

from rdflib import Literal, XSD

from extraction_pipeline.pipeline import EX, extract_retail_order_to_graph


def _with_deterministic_mode() -> None:
    os.environ["EXTRACTION_STRATEGY"] = "deterministic"


def test_extract_retail_order_to_graph_extracts_order_entities() -> None:
    _with_deterministic_mode()
    text = """ORDER: ORD-1001
DATE: 2026-05-30
CUSTOMER: CUST-001 | Alice Example
STORE: STR-AMS-CENTRAL | Amsterdam Central
ITEM: SKU-APPLE-001 | Gala Apples | qty=2 | unit=1.50
ITEM: SKU-BREAD-002 | Wholegrain Bread | qty=1 | unit=2.40
"""
    graph = extract_retail_order_to_graph(text, document_id="receipt-001")

    assert (EX["order-ord-1001"], EX.orderId, Literal("ORD-1001")) in graph
    assert (EX["customer-cust-001"], EX.customerName, Literal("Alice Example")) in graph
    assert (EX["store-str-ams-central"], EX.storeName, Literal("Amsterdam Central")) in graph
    assert (EX["product-sku-apple-001"], EX.productName, Literal("Gala Apples")) in graph
    assert (
        EX["order-ord-1001"],
        EX.totalAmount,
        Literal("5.40", datatype=XSD.decimal),
    ) in graph


def test_extract_retail_order_to_graph_requires_item_lines() -> None:
    _with_deterministic_mode()
    text = """ORDER: ORD-1002
DATE: 2026-05-31
CUSTOMER: CUST-002 | Bob Builder
STORE: STR-AMS-CENTRAL | Amsterdam Central
"""

    try:
        extract_retail_order_to_graph(text)
    except ValueError as exc:
        assert "ITEM" in str(exc)
        return
    raise AssertionError("Expected ValueError when no ITEM lines are present")
