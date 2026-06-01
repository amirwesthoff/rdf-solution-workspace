import argparse
import base64
import datetime as dt
import os
import re
import uuid
from pathlib import Path
from urllib import error, parse, request

from rdflib import Graph, Literal, Namespace, RDF, XSD

from .promote import promote_if_valid
from .validator import validate_graph_against_shapes

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
    headers = _auth_headers(username, password, accept="text/turtle")
    for key, value in headers.items():
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
    headers = _auth_headers(username, password)
    req.add_header("Content-Type", "text/turtle")
    for key, value in headers.items():
        req.add_header(key, value)
    with request.urlopen(req):
        pass


def _append_validation_run_report(
    report_graph: Graph,
    conforms: bool,
    report_text: str,
    raw_graph_iri: str,
    asserted_graph_iri: str,
) -> Graph:
    run_id = str(uuid.uuid4())
    run = EX[f"validation-run-{run_id}"]

    report_graph.bind("ex", EX)
    report_graph.add((run, RDF.type, EX.ValidationRun))
    report_graph.add((run, EX.sourceGraph, Literal(raw_graph_iri)))
    report_graph.add((run, EX.targetGraph, Literal(asserted_graph_iri)))
    report_graph.add((run, EX.conforms, Literal(conforms)))
    report_graph.add((run, EX.reportText, Literal(report_text)))
    report_graph.add(
        (
            run,
            EX.validatedAt,
            Literal(dt.datetime.now(dt.timezone.utc).isoformat(), datatype=XSD.dateTime),
        )
    )
    return report_graph


def run_validate_and_promote(args: argparse.Namespace) -> int:
    shapes_path = Path(args.shapes_path)
    if not shapes_path.exists():
        raise FileNotFoundError(f"Shapes file not found: {shapes_path}")

    backend = getattr(args, "backend", None) or _default_backend()

    raw_graph = _fetch_named_graph(
        args.base_url,
        args.dataset,
        args.raw_graph,
        args.username,
        args.password,
        backend,
    )
    if len(raw_graph) == 0:
        print(f"No triples found in raw graph '{args.raw_graph}'.")

    conforms, report_text = validate_graph_against_shapes(raw_graph, shapes_path)

    asserted_graph = _fetch_named_graph(
        args.base_url,
        args.dataset,
        args.asserted_graph,
        args.username,
        args.password,
        backend,
    )
    promoted = promote_if_valid(conforms, raw_graph, asserted_graph)
    if promoted:
        _put_named_graph(
            asserted_graph,
            args.base_url,
            args.dataset,
            args.asserted_graph,
            args.username,
            args.password,
            backend,
        )

    report_graph = _fetch_named_graph(
        args.base_url,
        args.dataset,
        args.report_graph,
        args.username,
        args.password,
        backend,
    )
    report_graph = _append_validation_run_report(
        report_graph,
        conforms=conforms,
        report_text=report_text,
        raw_graph_iri=args.raw_graph,
        asserted_graph_iri=args.asserted_graph,
    )
    _put_named_graph(
        report_graph,
        args.base_url,
        args.dataset,
        args.report_graph,
        args.username,
        args.password,
        backend,
    )

    print(f"Backend: {backend}")
    print(f"Conforms: {conforms}")
    print(f"Raw triple count: {len(raw_graph)}")
    print(f"Asserted triple count after run: {len(asserted_graph)}")
    print(f"Validation report graph updated: {args.report_graph}")

    if conforms:
        return 0
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate raw graph and promote if valid.")
    parser.add_argument("--base-url", default="http://localhost:3030")
    parser.add_argument("--dataset", default="kg")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--raw-graph", default="urn:graph:raw")
    parser.add_argument("--asserted-graph", default="urn:graph:asserted")
    parser.add_argument("--report-graph", default="urn:graph:validation-reports")
    parser.add_argument("--shapes-path", default="contracts/shapes/core.shacl.ttl")
    parser.add_argument("--backend", default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = run_validate_and_promote(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
