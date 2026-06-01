import argparse
import base64
import os
from pathlib import Path
from urllib import error, parse, request

import pytest
from rdflib import Graph

from qa_service.sparql import ask_fuseki
from validation_gate.cli import run_validate_and_promote
from validation_gate.infer import materialize_inferred_graph

BASE_URL = "http://localhost:3030"
DATASET = "kg"
USERNAME = "admin"
PASSWORD = "admin"
RAW_GRAPH = "urn:graph:raw"
ASSERTED_GRAPH = "urn:graph:asserted"
INFERRED_GRAPH = "urn:graph:inferred"
REPORT_GRAPH = "urn:graph:validation-reports"


def _auth_headers(accept: str | None = None) -> dict[str, str]:
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode("ascii")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    if accept:
        headers["Accept"] = accept
    return headers


def _graph_store_url(graph_iri: str) -> str:
    encoded_graph = parse.quote(graph_iri, safe="")
    return f"{BASE_URL}/{DATASET}/data?graph={encoded_graph}"


def _is_fuseki_available() -> bool:
    ping_url = f"{BASE_URL}/$/ping"
    req = request.Request(ping_url, method="GET")
    for key, value in _auth_headers().items():
        req.add_header(key, value)
    try:
        with request.urlopen(req):
            return True
    except Exception:
        return False


def _put_graph(graph_iri: str, graph: Graph) -> None:
    body = graph.serialize(format="turtle").encode("utf-8")
    req = request.Request(_graph_store_url(graph_iri), data=body, method="PUT")
    req.add_header("Content-Type", "text/turtle")
    for key, value in _auth_headers().items():
        req.add_header(key, value)
    with request.urlopen(req):
        pass


def _fetch_graph(graph_iri: str) -> Graph:
    req = request.Request(_graph_store_url(graph_iri), method="GET")
    for key, value in _auth_headers(accept="text/turtle").items():
        req.add_header(key, value)

    graph = Graph()
    try:
        with request.urlopen(req) as response:
            body = response.read().decode("utf-8")
            if body.strip():
                graph.parse(data=body, format="turtle")
    except error.HTTPError as exc:
        if exc.code not in (404,):
            raise
    return graph


def _reset_graphs() -> None:
    empty = Graph()
    _put_graph(ASSERTED_GRAPH, empty)
    _put_graph(INFERRED_GRAPH, empty)
    _put_graph(REPORT_GRAPH, empty)


@pytest.mark.integration
def test_end_to_end_pipeline_validate_infer_and_qa() -> None:
    if not _is_fuseki_available():
        pytest.skip("Fuseki not available on localhost:3030")

    sample_path = Path("contracts/sample-data/sample.ttl")
    sample_graph = Graph().parse(sample_path)

    _reset_graphs()
    _put_graph(RAW_GRAPH, sample_graph)

    args = argparse.Namespace(
        base_url=BASE_URL,
        dataset=DATASET,
        username=USERNAME,
        password=PASSWORD,
        raw_graph=RAW_GRAPH,
        asserted_graph=ASSERTED_GRAPH,
        report_graph=REPORT_GRAPH,
        shapes_path="contracts/shapes/core.shacl.ttl",
        backend="fuseki",
    )
    exit_code = run_validate_and_promote(args)
    assert exit_code == 0

    asserted = _fetch_graph(ASSERTED_GRAPH)
    assert len(asserted) > 10

    inferred = materialize_inferred_graph(asserted)
    _put_graph(INFERRED_GRAPH, inferred)
    assert len(inferred) >= 1

    prior_backend = os.environ.get("GRAPH_BACKEND")
    os.environ["GRAPH_BACKEND"] = "fuseki"
    qa_result = ask_fuseki("Who are the customers?")
    if prior_backend is None:
        os.environ.pop("GRAPH_BACKEND", None)
    else:
        os.environ["GRAPH_BACKEND"] = prior_backend
    assert qa_result.sparql
    assert qa_result.rows
    assert any(row.get("name") == "Alice Example" for row in qa_result.rows)
