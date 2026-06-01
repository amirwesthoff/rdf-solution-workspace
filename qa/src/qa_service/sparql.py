import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import parse, request

from rdflib import Dataset, URIRef


@dataclass
class QAResult:
    answer: str
    sparql: str
    rows: list[dict[str, str]]


def _fuseki_query_url(base_url: str, dataset: str, sparql: str) -> str:
    encoded_query = parse.quote(sparql, safe="")
    return f"{base_url.rstrip('/')}/{dataset}/sparql?query={encoded_query}"


def _default_backend() -> str:
    return os.getenv("GRAPH_BACKEND", "rdflib").strip().lower()


def _store_dir() -> Path:
    return Path(os.getenv("RDFLIB_STORE_DIR", "data/graph-store"))


def _graph_file_name(graph_iri: str) -> str:
    known = {
        "urn:graph:raw": "raw.ttl",
        "urn:graph:asserted": "asserted.ttl",
        "urn:graph:inferred": "inferred.ttl",
        "urn:graph:validation-reports": "validation-reports.ttl",
    }
    if graph_iri in known:
        return known[graph_iri]
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", graph_iri).strip("-")
    return f"{slug}.ttl"


def _execute_select_query_rdflib(sparql: str) -> list[dict[str, str]]:
    dataset = Dataset()
    for graph_iri in ("urn:graph:asserted", "urn:graph:inferred"):
        file_path = _store_dir() / _graph_file_name(graph_iri)
        if not file_path.exists():
            continue
        dataset.graph(URIRef(graph_iri)).parse(file_path)

    query_result = dataset.query(sparql)
    rows: list[dict[str, str]] = []
    for row in query_result:
        row_map: dict[str, str] = {}
        for var in query_result.vars:
            value = row.get(var)
            if value is not None:
                row_map[str(var)] = str(value)
        rows.append(row_map)
    return rows


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/sparql-results+json",
    }


def execute_select_query(
    sparql: str,
    base_url: str,
    dataset: str,
    username: str,
    password: str,
    backend: str,
) -> list[dict[str, str]]:
    if backend == "rdflib":
        return _execute_select_query_rdflib(sparql)

    if backend != "fuseki":
        raise ValueError("Unsupported backend. Use 'rdflib' (default) or 'fuseki'.")

    url = _fuseki_query_url(base_url, dataset, sparql)
    req = request.Request(url, method="GET")
    for key, value in _auth_headers(username, password).items():
        req.add_header(key, value)

    with request.urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows: list[dict[str, str]] = []
    for binding in payload.get("results", {}).get("bindings", []):
        row: dict[str, str] = {}
        for var_name, var_data in binding.items():
            row[var_name] = var_data.get("value", "")
        rows.append(row)
    return rows


def _default_config() -> tuple[str, str, str, str]:
    return (
        os.getenv("FUSEKI_BASE_URL", "http://localhost:3030"),
        os.getenv("FUSEKI_DATASET", "kg"),
        os.getenv("FUSEKI_USERNAME", "admin"),
        os.getenv("FUSEKI_PASSWORD", "admin"),
    )


def question_to_sparql(question: str) -> QAResult:
    """Map known intents to deterministic SPARQL templates."""
    q = question.lower().strip()

    if "top product" in q or "most ordered" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT ?productName (SUM(?qty) AS ?totalUnits)\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?line a ex:OrderLine ;\n"
            "      ex:lineProduct ?product ;\n"
            "      ex:lineQuantity ?qty .\n"
            "    ?product ex:productName ?productName .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "GROUP BY ?productName\n"
            "ORDER BY DESC(?totalUnits)"
        )
        return QAResult(answer="Top products query generated.", sparql=sparql, rows=[])

    if "total" in q and "order" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT ?orderId ?customerName ?total\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?order a ex:Order ;\n"
            "      ex:orderId ?orderId ;\n"
            "      ex:placedBy ?customer ;\n"
            "      ex:totalAmount ?total .\n"
            "    ?customer ex:customerName ?customerName .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "ORDER BY ?orderId"
        )
        return QAResult(answer="Order totals query generated.", sparql=sparql, rows=[])

    if "product mix" in q or "mix" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT ?productName (SUM(?qty) AS ?units)\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?line a ex:OrderLine ;\n"
            "      ex:lineProduct ?product ;\n"
            "      ex:lineQuantity ?qty .\n"
            "    ?product ex:productName ?productName .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "GROUP BY ?productName\n"
            "ORDER BY DESC(?units)"
        )
        return QAResult(answer="Product mix query generated.", sparql=sparql, rows=[])

    if "repeat customer" in q or "repeat customers" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT ?customer ?name (COUNT(?order) AS ?orderCount)\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?order a ex:Order ;\n"
            "      ex:placedBy ?customer .\n"
            "    ?customer ex:customerName ?name .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "GROUP BY ?customer ?name\n"
            "HAVING (COUNT(?order) > 1)\n"
            "ORDER BY DESC(?orderCount)"
        )
        return QAResult(answer="Repeat customers query generated.", sparql=sparql, rows=[])

    if "daily revenue" in q or "store revenue" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT ?storeName ?orderDate (SUM(?total) AS ?dailyRevenue)\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?order a ex:Order ;\n"
            "      ex:orderDate ?orderDate ;\n"
            "      ex:soldAtStore ?store ;\n"
            "      ex:totalAmount ?total .\n"
            "    ?store ex:storeName ?storeName .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "GROUP BY ?storeName ?orderDate\n"
            "ORDER BY ?orderDate ?storeName"
        )
        return QAResult(answer="Store daily revenue query generated.", sparql=sparql, rows=[])

    if "customer" in q or "who" in q or "people" in q:
        sparql = (
            "PREFIX ex: <http://example.org/kg/>\n\n"
            "SELECT DISTINCT ?customer ?name\n"
            "WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?customer a ex:Customer ;\n"
            "      ex:customerName ?name .\n"
            "  }\n"
            "  FILTER(?g IN (<urn:graph:asserted>, <urn:graph:inferred>))\n"
            "}\n"
            "ORDER BY ?name"
        )
        return QAResult(answer="Customer query generated.", sparql=sparql, rows=[])

    return QAResult(answer="I do not understand the question yet.", sparql="", rows=[])


def ask_fuseki(question: str) -> QAResult:
    """Generate and execute a deterministic SPARQL query against Fuseki."""
    result = question_to_sparql(question)
    if not result.sparql:
        return result

    base_url, dataset, username, password = _default_config()
    backend = _default_backend()
    rows = execute_select_query(
        sparql=result.sparql,
        base_url=base_url,
        dataset=dataset,
        username=username,
        password=password,
        backend=backend,
    )

    if rows:
        return QAResult(
            answer=f"Found {len(rows)} result(s).",
            sparql=result.sparql,
            rows=rows,
        )

    return QAResult(answer="No results found.", sparql=result.sparql, rows=[])
