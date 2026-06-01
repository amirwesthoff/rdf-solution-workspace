import os

from qa_service.verbalizer import verbalize_query_results


def test_verbalize_query_results_fallback_no_key() -> None:
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["QA_USE_LLM_VERBALIZATION"] = "true"

    narrative, source = verbalize_query_results(
        question="Who are the customers?",
        sparql="SELECT ?name WHERE { }",
        rows=[{"name": "Alice Example"}, {"name": "Bob Builder"}],
    )

    assert source == "fallback"
    assert "Found 2 results" in narrative


def test_verbalize_query_results_fallback_disabled() -> None:
    os.environ["QA_USE_LLM_VERBALIZATION"] = "false"
    narrative, source = verbalize_query_results(
        question="Who are the customers?",
        sparql="SELECT ?name WHERE { }",
        rows=[],
    )

    assert source == "fallback"
    assert "No results" in narrative
