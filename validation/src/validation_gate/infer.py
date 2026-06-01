import argparse
import base64
import os
import re
from urllib import parse, request

from urllib import error
from pathlib import Path

from rdflib import Graph, Namespace

EX = Namespace("http://example.org/kg/")


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


def _fetch_named_graph_disk(graph_iri: str) -> Graph:
    graph = Graph()
    file_path = _store_dir() / _graph_file_name(graph_iri)
    if file_path.exists():
        graph.parse(file_path)
    return graph


def _put_named_graph_disk(graph: Graph, graph_iri: str) -> None:
    target_dir = _store_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / _graph_file_name(graph_iri)
    graph.serialize(destination=str(file_path), format="turtle")


def _auth_headers(username: str, password: str, accept: str | None = None) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    if accept:
        headers["Accept"] = accept
    return headers


def _graph_store_url(base_url: str, dataset: str, graph_iri: str) -> str:
    encoded_graph = parse.quote(graph_iri, safe="")
    return f"{base_url.rstrip('/')}/{dataset}/data?graph={encoded_graph}"


def _fetch_named_graph(
    base_url: str,
    dataset: str,
    graph_iri: str,
    username: str,
    password: str,
    backend: str,
) -> Graph:
    if backend == "rdflib":
        return _fetch_named_graph_disk(graph_iri)

    if backend != "fuseki":
        raise ValueError("Unsupported backend. Use 'rdflib' (default) or 'fuseki'.")

    url = _graph_store_url(base_url, dataset, graph_iri)
    req = request.Request(url, method="GET")
    for key, value in _auth_headers(username, password, accept="text/turtle").items():
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


def _put_named_graph(
    graph: Graph,
    base_url: str,
    dataset: str,
    graph_iri: str,
    username: str,
    password: str,
    backend: str,
) -> None:
    if backend == "rdflib":
        _put_named_graph_disk(graph, graph_iri)
        return

    if backend != "fuseki":
        raise ValueError("Unsupported backend. Use 'rdflib' (default) or 'fuseki'.")

    url = _graph_store_url(base_url, dataset, graph_iri)
    body = graph.serialize(format="turtle")
    req = request.Request(url, data=body.encode("utf-8"), method="PUT")
    req.add_header("Content-Type", "text/turtle")
    for key, value in _auth_headers(username, password).items():
        req.add_header(key, value)
    with request.urlopen(req):
        pass


def materialize_inferred_graph(asserted_graph: Graph) -> Graph:
    """Materialize simple inferred links from asserted data.

    Rule: if Order placedBy Customer and hasLine with lineProduct Product,
    infer Customer orderedProduct Product.
    """
    inferred = Graph()
    inferred.bind("ex", EX)

    for order, _, customer in asserted_graph.triples((None, EX.placedBy, None)):
        for line in asserted_graph.objects(order, EX.hasLine):
            for product in asserted_graph.objects(line, EX.lineProduct):
                inferred.add((customer, EX.orderedProduct, product))

    return inferred


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize inferred graph from asserted graph.")
    parser.add_argument("--base-url", default="http://localhost:3030")
    parser.add_argument("--dataset", default="kg")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--asserted-graph", default="urn:graph:asserted")
    parser.add_argument("--inferred-graph", default="urn:graph:inferred")
    parser.add_argument("--backend", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    backend = (args.backend or _default_backend()).strip().lower()
    asserted = _fetch_named_graph(
        args.base_url,
        args.dataset,
        args.asserted_graph,
        args.username,
        args.password,
        backend,
    )
    inferred = materialize_inferred_graph(asserted)
    _put_named_graph(
        inferred,
        args.base_url,
        args.dataset,
        args.inferred_graph,
        args.username,
        args.password,
        backend,
    )

    print(f"Backend: {backend}")
    print(f"Asserted triple count: {len(asserted)}")
    print(f"Inferred triple count written: {len(inferred)}")


if __name__ == "__main__":
    main()