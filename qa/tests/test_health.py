from fastapi.testclient import TestClient

from qa_service.main import app
from qa_service.sparql import QAResult
import qa_service.main as qa_main


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ask_endpoint_includes_narrative(monkeypatch) -> None:
    def fake_ask_fuseki(question: str) -> QAResult:
        return QAResult(
            answer="Found 1 result(s).",
            sparql="SELECT ?name WHERE {}",
            rows=[{"name": "Alice Example"}],
        )

    monkeypatch.setattr(qa_main, "ask_fuseki", fake_ask_fuseki)

    client = TestClient(app)
    response = client.post("/ask", json={"question": "Who are the customers?"})
    assert response.status_code == 200
    payload = response.json()
    assert "narrative" in payload
    assert "narrativeSource" in payload


def test_ask_endpoint_rdflib_smoke(tmp_path, monkeypatch) -> None:
    store_dir = tmp_path / "graph-store"
    store_dir.mkdir(parents=True, exist_ok=True)
    asserted_path = store_dir / "asserted.ttl"
    asserted_path.write_text(
        """
@prefix ex: <http://example.org/kg/> .

ex:cust-001 a ex:Customer ;
    ex:customerName \"Alice Example\" .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("GRAPH_BACKEND", "rdflib")
    monkeypatch.setenv("RDFLIB_STORE_DIR", str(store_dir))
    monkeypatch.setenv("QA_USE_LLM_VERBALIZATION", "false")

    client = TestClient(app)
    response = client.post("/ask", json={"question": "Who are the customers?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Found 1 result(s)."
    assert payload["narrativeSource"] == "fallback"
    assert payload["results"] == [
        {
            "customer": "http://example.org/kg/cust-001",
            "name": "Alice Example",
        }
    ]
