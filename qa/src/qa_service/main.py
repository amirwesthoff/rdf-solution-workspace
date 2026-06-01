from fastapi import FastAPI
from pydantic import BaseModel

from .sparql import ask_fuseki
from .verbalizer import verbalize_query_results

app = FastAPI(title="RDF QA Service", version="0.1.0")


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest) -> dict[str, object]:
    result = ask_fuseki(req.question)
    narrative, narrative_source = verbalize_query_results(
        question=req.question,
        sparql=result.sparql,
        rows=result.rows,
    )
    return {
        "answer": result.answer,
        "narrative": narrative,
        "narrativeSource": narrative_source,
        "sparql": result.sparql,
        "results": result.rows,
    }
