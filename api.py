"""API del RAG para conectar el frontend del chat.

Ejecutar:
    uvicorn api:app --reload --host 127.0.0.1 --port 8000
"""
import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, StringConstraints

from rag.answer import answer

logger = logging.getLogger(__name__)

app = FastAPI(title="RAG normas ISO", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Pregunta(BaseModel):
    pregunta: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=2000,
        ),
    ]


@app.get("/health")
def health():
    """Comprueba que la API está encendida."""
    return {"ok": True}


@app.post("/preguntar")
def preguntar(body: Pregunta):
    """Devuelve la respuesta y los fragmentos recuperados."""
    try:
        result = answer(body.pregunta)
        if not result.get("answer", "").strip():
            raise RuntimeError("El modelo devolvió una respuesta vacía.")
        return result
    except Exception:
        logger.exception("Error al responder la consulta")
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo completar la consulta. "
                "Intentá nuevamente en unos instantes."
            ),
        ) from None