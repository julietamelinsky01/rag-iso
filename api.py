"""API HTTP mínima (para conectar una web, n8n u Open WebUI más adelante).

Uso:
    uvicorn api:app --reload
    POST http://localhost:8000/preguntar   {"pregunta": "..."}
"""
from fastapi import FastAPI
from pydantic import BaseModel

from rag.answer import answer

app = FastAPI(title="RAG normas ISO")


class Pregunta(BaseModel):
    pregunta: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/preguntar")
def preguntar(body: Pregunta):
    return answer(body.pregunta)
