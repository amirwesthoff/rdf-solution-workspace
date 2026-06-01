from pathlib import Path
from pyshacl import validate
from rdflib import Graph, Namespace, RDF

EX = Namespace("http://example.org/kg/")


def _business_rule_violations(data_graph: Graph) -> list[str]:
    violations: list[str] = []

    order_id_to_subjects: dict[str, list[str]] = {}
    sku_to_name: dict[str, str] = {}

    for order in data_graph.subjects(RDF.type, EX.Order):
        order_str = str(order)
        order_id_values = [str(o) for o in data_graph.objects(order, EX.orderId)]
        for order_id in order_id_values:
            order_id_to_subjects.setdefault(order_id, []).append(order_str)

    for product in data_graph.subjects(RDF.type, EX.Product):
        product_str = str(product)
        sku_values = [str(o) for o in data_graph.objects(product, EX.sku)]
        name_values = [str(o) for o in data_graph.objects(product, EX.productName)]

        if sku_values and name_values:
            sku = sku_values[0]
            product_name = name_values[0]
            if sku in sku_to_name and sku_to_name[sku] != product_name:
                violations.append(
                    f"Business rule violation: SKU '{sku}' has inconsistent product names ('{sku_to_name[sku]}' and '{product_name}')."
                )
            sku_to_name[sku] = product_name
        elif sku_values and not name_values:
            violations.append(
                f"Business rule violation: Product '{product_str}' has sku but no productName."
            )

    for order_id, subjects in order_id_to_subjects.items():
        if order_id and len(subjects) > 1:
            subject_list = ", ".join(sorted(subjects))
            violations.append(
                f"Business rule violation: Duplicate orderId '{order_id}' found for subjects: {subject_list}."
            )

    return violations


def validate_graph_against_shapes(data_graph: Graph, shapes_path: Path) -> tuple[bool, str]:
    """Validate RDF data with SHACL plus business rules.

    Returns a tuple of overall conformance and a combined human-readable report.
    """
    shapes_graph = Graph().parse(shapes_path)
    shacl_conforms, _, report_text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=True,
    )
    business_violations = _business_rule_violations(data_graph)

    report_parts = ["SHACL validation report:", str(report_text).strip()]
    if business_violations:
        report_parts.append("Business rule violations:")
        report_parts.extend(f"- {item}" for item in business_violations)
    else:
        report_parts.append("Business rule violations:\n- None")

    overall_conforms = bool(shacl_conforms) and not business_violations
    return overall_conforms, "\n".join(report_parts)
