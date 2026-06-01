import argparse
import base64
import os
import re
from pathlib import Path
from urllib import parse, request

from rdflib import Graph

from .pipeline import extract_retail_order_to_graph


def _graph_store_url(base_url: str, dataset: str, graph_iri: str) -> str:
    encoded_graph = parse.quote(graph_iri, safe="")
    return f"{base_url.rstrip('/')}/{dataset}/data?graph={encoded_graph}"


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


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


def _write_graph_disk(graph_ttl: str, graph_iri: str) -> Path:
    target_dir = _store_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / _graph_file_name(graph_iri)

    # Parse first so invalid RDF is never persisted.
    graph = Graph()
    graph.parse(data=graph_ttl, format="turtle")
    graph.serialize(destination=str(target_file), format="turtle")
    return target_file


def upload_graph(
    graph_ttl: str,
    base_url: str,
    dataset: str,
    graph_iri: str,
    username: str,
    password: str,
    backend: str,
) -> None:
    if backend == "rdflib":
        _write_graph_disk(graph_ttl=graph_ttl, graph_iri=graph_iri)
        return

    if backend == "fuseki":
        url = _graph_store_url(base_url, dataset, graph_iri)
        req = request.Request(url, data=graph_ttl.encode("utf-8"), method="PUT")
        req.add_header("Content-Type", "text/turtle")
        for key, value in _auth_headers(username, password).items():
            req.add_header(key, value)
        with request.urlopen(req):
            pass
        return

    raise ValueError("Unsupported backend. Use 'rdflib' (default) or 'fuseki'.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract structured retail RDF from unstructured text and upload to Fuseki raw graph."
    )
    parser.add_argument("--input", default="examples/unstructured-retail-order.txt")
    parser.add_argument("--document-id", default="retail-doc-llm-001")
    parser.add_argument("--base-url", default="http://localhost:3030")
    parser.add_argument("--dataset", default="kg")
    parser.add_argument("--graph", default="urn:graph:raw")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--backend", default=None)
    parser.add_argument("--print-ttl", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    text = input_path.read_text(encoding="utf-8")
    graph = extract_retail_order_to_graph(text=text, document_id=args.document_id)
    ttl = graph.serialize(format="turtle")
    backend = (args.backend or _default_backend()).strip().lower()

    upload_graph(
        graph_ttl=ttl,
        base_url=args.base_url,
        dataset=args.dataset,
        graph_iri=args.graph,
        username=args.username,
        password=args.password,
        backend=backend,
    )

    print(f"Input file: {input_path}")
    print(f"Extraction strategy: default (EXTRACTION_STRATEGY env, default=llm)")
    print(f"Graph backend: {backend}")
    print(f"Triples extracted: {len(graph)}")
    print(f"Uploaded to graph: {args.graph}")

    if args.print_ttl:
        print("--- RDF Turtle ---")
        print(ttl)


if __name__ == "__main__":
    main()
