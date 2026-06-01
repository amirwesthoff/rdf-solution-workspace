from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, XSD
from validation_gate.validator import validate_graph_against_shapes

EX = Namespace("http://example.org/kg/")


def test_validate_graph_against_shapes_passes_sample() -> None:
    data = Graph().parse("contracts/sample-data/sample.ttl")
    conforms, _ = validate_graph_against_shapes(
        data_graph=data,
        shapes_path=Path("contracts/shapes/core.shacl.ttl"),
    )
    assert conforms


def test_validate_graph_against_shapes_fails_duplicate_order_id() -> None:
    data = Graph()
    data.bind("ex", EX)

    customer = EX["customer-cust-001"]
    store = EX["store-str-ams-central"]
    product = EX["product-sku-apple-001"]
    line1 = EX["orderline-1"]
    line2 = EX["orderline-2"]
    order1 = EX["order-a"]
    order2 = EX["order-b"]

    data.add((customer, RDF.type, EX.Customer))
    data.add((customer, EX.customerId, Literal("CUST-001")))
    data.add((customer, EX.customerName, Literal("Alice Example")))
    data.add((store, RDF.type, EX.Store))
    data.add((store, EX.storeId, Literal("STR-AMS-CENTRAL")))
    data.add((store, EX.storeName, Literal("Amsterdam Central")))
    data.add((product, RDF.type, EX.Product))
    data.add((product, EX.sku, Literal("SKU-APPLE-001")))
    data.add((product, EX.productName, Literal("Gala Apples")))
    data.add((product, EX.listPrice, Literal("1.50", datatype=XSD.decimal)))

    data.add((line1, RDF.type, EX.OrderLine))
    data.add((line1, EX.lineProduct, product))
    data.add((line1, EX.lineQuantity, Literal(1, datatype=XSD.integer)))
    data.add((line1, EX.lineUnitPrice, Literal("1.50", datatype=XSD.decimal)))
    data.add((line1, EX.lineTotal, Literal("1.50", datatype=XSD.decimal)))

    data.add((line2, RDF.type, EX.OrderLine))
    data.add((line2, EX.lineProduct, product))
    data.add((line2, EX.lineQuantity, Literal(1, datatype=XSD.integer)))
    data.add((line2, EX.lineUnitPrice, Literal("1.50", datatype=XSD.decimal)))
    data.add((line2, EX.lineTotal, Literal("1.50", datatype=XSD.decimal)))

    for order, line in ((order1, line1), (order2, line2)):
        data.add((order, RDF.type, EX.Order))
        data.add((order, EX.orderId, Literal("ORD-9000")))
        data.add((order, EX.orderDate, Literal("2026-05-31", datatype=XSD.date)))
        data.add((order, EX.placedBy, customer))
        data.add((order, EX.soldAtStore, store))
        data.add((order, EX.hasLine, line))
        data.add((order, EX.totalAmount, Literal("1.50", datatype=XSD.decimal)))

    conforms, report = validate_graph_against_shapes(
        data_graph=data,
        shapes_path=Path("contracts/shapes/core.shacl.ttl"),
    )

    assert not conforms
    assert "Duplicate orderId" in report


def test_validate_graph_against_shapes_fails_order_total_mismatch() -> None:
    data = Graph()
    data.bind("ex", EX)

    customer = EX["customer-cust-003"]
    store = EX["store-str-ams-central"]
    product = EX["product-sku-bread-002"]
    line = EX["orderline-3"]
    order = EX["order-mismatch"]

    data.add((customer, RDF.type, EX.Customer))
    data.add((customer, EX.customerId, Literal("CUST-003")))
    data.add((customer, EX.customerName, Literal("Casey Shopper")))
    data.add((store, RDF.type, EX.Store))
    data.add((store, EX.storeId, Literal("STR-AMS-CENTRAL")))
    data.add((store, EX.storeName, Literal("Amsterdam Central")))
    data.add((product, RDF.type, EX.Product))
    data.add((product, EX.sku, Literal("SKU-BREAD-002")))
    data.add((product, EX.productName, Literal("Wholegrain Bread")))
    data.add((product, EX.listPrice, Literal("2.40", datatype=XSD.decimal)))

    data.add((line, RDF.type, EX.OrderLine))
    data.add((line, EX.lineProduct, product))
    data.add((line, EX.lineQuantity, Literal(1, datatype=XSD.integer)))
    data.add((line, EX.lineUnitPrice, Literal("2.40", datatype=XSD.decimal)))
    data.add((line, EX.lineTotal, Literal("2.40", datatype=XSD.decimal)))

    data.add((order, RDF.type, EX.Order))
    data.add((order, EX.orderId, Literal("ORD-9010")))
    data.add((order, EX.orderDate, Literal("2026-05-31", datatype=XSD.date)))
    data.add((order, EX.placedBy, customer))
    data.add((order, EX.soldAtStore, store))
    data.add((order, EX.hasLine, line))
    data.add((order, EX.totalAmount, Literal("3.10", datatype=XSD.decimal)))

    conforms, report = validate_graph_against_shapes(
        data_graph=data,
        shapes_path=Path("contracts/shapes/core.shacl.ttl"),
    )

    assert not conforms
    assert "totalAmount must equal the sum of lineTotal values" in report


def test_validate_graph_against_shapes_fails_line_math_constraint() -> None:
    data = Graph()
    data.bind("ex", EX)

    customer = EX["customer-cust-010"]
    store = EX["store-str-ams-central"]
    product = EX["product-sku-milk-003"]
    line = EX["orderline-10"]
    order = EX["order-line-math"]

    data.add((customer, RDF.type, EX.Customer))
    data.add((customer, EX.customerId, Literal("CUST-010")))
    data.add((customer, EX.customerName, Literal("Dana Buyer")))

    data.add((store, RDF.type, EX.Store))
    data.add((store, EX.storeId, Literal("STR-AMS-CENTRAL")))
    data.add((store, EX.storeName, Literal("Amsterdam Central")))

    data.add((product, RDF.type, EX.Product))
    data.add((product, EX.sku, Literal("SKU-MILK-003")))
    data.add((product, EX.productName, Literal("Semi-Skimmed Milk")))
    data.add((product, EX.listPrice, Literal("1.20", datatype=XSD.decimal)))

    data.add((line, RDF.type, EX.OrderLine))
    data.add((line, EX.lineProduct, product))
    data.add((line, EX.lineQuantity, Literal(2, datatype=XSD.integer)))
    data.add((line, EX.lineUnitPrice, Literal("1.20", datatype=XSD.decimal)))
    data.add((line, EX.lineTotal, Literal("2.30", datatype=XSD.decimal)))

    data.add((order, RDF.type, EX.Order))
    data.add((order, EX.orderId, Literal("ORD-9020")))
    data.add((order, EX.orderDate, Literal("2026-05-31", datatype=XSD.date)))
    data.add((order, EX.placedBy, customer))
    data.add((order, EX.soldAtStore, store))
    data.add((order, EX.hasLine, line))
    data.add((order, EX.totalAmount, Literal("2.30", datatype=XSD.decimal)))

    conforms, report = validate_graph_against_shapes(
        data_graph=data,
        shapes_path=Path("contracts/shapes/core.shacl.ttl"),
    )

    assert not conforms
    assert "lineTotal must equal lineQuantity * lineUnitPrice" in report
