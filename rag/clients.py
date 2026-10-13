"""Conexión a Supabase y modelos locales de Ollama."""
import json
import re
from functools import lru_cache
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from supabase import Client, create_client
from rag import config


@lru_cache
def supabase() -> Client:
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "Completá SUPABASE_URL y SUPABASE_SERVICE_KEY en .env."
        )
    return create_client(
        config.SUPABASE_URL,
        config.SUPABASE_SERVICE_KEY,
    )


def ollama_request(endpoint: str, payload: dict) -> dict:
    request = Request(
        config.OLLAMA_URL + endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"Ollama devolvió HTTP {exc.code}. Revisá los modelos "
            "descargados y el tamaño del texto."
        ) from None
    except (URLError, TimeoutError):
        raise RuntimeError(
            "No se pudo consultar Ollama. Abrí la aplicación."
        ) from None

    if result.get("error"):
        raise RuntimeError("Ollama no pudo procesar la solicitud.")

    return result


def embed(
    texts: list[str], *, query: bool = False
) -> list[list[float]]:
    vectors = []
    prefix = (
        "task: search result | query: "
        if query
        else "title: none | text: "
    )

    for start in range(0, len(texts), 8):
        batch = texts[start:start + 8]
        result = ollama_request(
            "/api/embed",
            {
                "model": config.EMBEDDING_MODEL,
                "input": [prefix + text for text in batch],
                "truncate": False,
            },
        )

        received = result.get("embeddings", [])
        if len(received) != len(batch) or any(
            len(vector) != config.EMBEDDING_DIM
            for vector in received
        ):
            raise RuntimeError(
                "Se esperaban vectores de 768 dimensiones."
            )

        vectors.extend(received)

    return vectors


def generate(system: str, user: str) -> str:
    result = ollama_request(
        "/api/chat",
        {
            "model": config.CHAT_MODEL,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\n/no_think"},
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": 8192,
                "num_predict": 1200,
            },
        },
    )

    text = result.get("message", {}).get("content", "")

    # Algunas plantillas incluyen razonamiento dentro del contenido.
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:
        raise RuntimeError(
            "El modelo no terminó de generar la respuesta."
        )

    text = re.sub(r"</?think>", "", text).strip()

    if result.get("done_reason") == "length":
        raise RuntimeError(
            "La respuesta alcanzó el límite. "
            "Probá una pregunta más específica."
        )

    if not text:
        raise RuntimeError("El modelo devolvió una respuesta vacía.")

    return text