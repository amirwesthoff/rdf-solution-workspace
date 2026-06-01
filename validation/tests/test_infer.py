from rdflib import Graph, Namespace

from validation_gate.infer import materialize_inferred_graph

EX = Namespace("http://example.org/kg/")


def test_materialize_inferred_graph_adds_customer_ordered_product() -> None:
    asserted = Graph()
    asserted.bind("ex", EX)

    asserted.add((EX["order-1001"], EX.placedBy, EX["customer-cust-001"]))
    asserted.add((EX["order-1001"], EX.hasLine, EX["orderline-1001-1"]))
    asserted.add((EX["orderline-1001-1"], EX.lineProduct, EX["product-sku-apple-001"]))

    inferred = materialize_inferred_graph(asserted)

    assert (
        EX["customer-cust-001"],
        EX.orderedProduct,
        EX["product-sku-apple-001"],
    ) in inferred