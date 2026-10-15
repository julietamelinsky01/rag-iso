"""Prepara documentos para el RAG y carga archivos locales.

Uso:
    python ingest.py docs/Manual_Prueba_RAG.pdf
    python ingest.py docs/
    python ingest.py docs/ISO_9001.pdf --norma "ISO 9001:2015"

prepare_file() extrae, fragmenta y genera embeddings validados; también
la usa sync_drive.py. La carga local reemplaza el documento de forma
atómica con public.replace_document y lo deja activo.

Los documentos administrados desde Drive se actualizan con sync_drive.py,
no con este script.
"""
import argparse
import math
from pathlib import Path

from rag.chunker import chunk_pages
from rag.clients import embed, supabase
from rag.loaders import load_document

EXTS = {".pdf", ".docx", ".txt", ".md"}
EMBEDDING_DIM = 768


def prepare_file(path: Path, label: str | None = None) -> list[dict]:
    """Devuelve los fragmentos listos para guardar, o lanza un error.

    label es el nombre a mostrar (por ejemplo, el nombre en Drive).
    """
    path = Path(path)
    label = label or path.name

    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo: {path}")
    if path.suffix.lower() not in EXTS:
        raise ValueError(f"Formato no admitido: {path.suffix}")

    print(f"\n📄 {label}", flush=True)

    pages = load_document(str(path))
    chunks = chunk_pages(pages)

    if not chunks:
        raise ValueError(
            "No se extrajo texto. Revisá si el documento necesita OCR."
        )

    for index, chunk in enumerate(chunks):
        if not chunk.content or not chunk.content.strip():
            raise ValueError(f"El fragmento {index} no tiene texto.")

    clausulas = sum(1 for chunk in chunks if chunk.clausula)
    print(
        f"   {len(pages)} página(s) → {len(chunks)} fragmentos "
        f"({clausulas} con cláusula detectada)",
        flush=True,
    )

    texts = [
        f"{chunk.clausula or ''} {chunk.titulo or ''}\n"
        f"{chunk.content}".strip()
        for chunk in chunks
    ]

    print("   Generando embeddings...", flush=True)
    vectors = embed(texts)

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "La cantidad de embeddings no coincide con los fragmentos."
        )

    rows = []
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"El vector {index} tiene {len(vector)} dimensiones; "
                f"se esperaban {EMBEDDING_DIM}."
            )

        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"El vector {index} contiene valores inválidos.")
        if not any(value != 0 for value in values):
            raise ValueError(f"El vector {index} es un vector cero.")

        rows.append(
            {
                "clausula": chunk.clausula,
                "titulo": chunk.titulo,
                "pagina": chunk.pagina,
                "content": chunk.content,
                "embedding": values,
            }
        )

    return rows


def ingest_file(path: Path, norma: str | None = None) -> None:
    """Carga un archivo local que no está administrado por Drive."""
    path = Path(path)
    db = supabase()

    # Evita una copia local de un documento que ya llega desde Drive.
    managed = (
        db.table("drive_sync_state")
        .select("file_id")
        .eq("file_name", path.name)
        .limit(1)
        .execute()
        .data
    )
    if managed:
        raise ValueError(
            "Este documento está administrado por Drive. "
            "Actualizalo allí y ejecutá sync_drive.py."
        )

    rows = prepare_file(path)

    print("   Guardando documento en Supabase...", flush=True)

    # Una única llamada: la función SQL reemplaza todos los fragmentos
    # en una transacción. Si falla, se conserva la versión anterior.
    result = db.rpc(
        "replace_document",
        {
            "p_source": path.name,
            "p_title": path.stem,
            "p_norma": norma,
            "p_chunks": rows,
        },
    ).execute()

    print(
        f"   ✅ cargado: {len(rows)} fragmentos "
        f"(documento ID: {result.data})",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cargar documentos locales al RAG con reemplazo atómico"
    )
    parser.add_argument("ruta", help="Archivo o carpeta")
    parser.add_argument(
        "--norma",
        help='Nombre de la norma, por ejemplo: "ISO 9001:2015"',
    )
    args = parser.parse_args()

    ruta = Path(args.ruta).expanduser()

    if not ruta.exists():
        parser.error(f"No existe la ruta: {ruta}")

    files = (
        [ruta]
        if ruta.is_file()
        else sorted(
            path
            for path in ruta.rglob("*")
            if path.is_file() and path.suffix.lower() in EXTS
        )
    )

    if not files:
        print("No encontré documentos para cargar.")
        return

    errors = 0
    for path in files:
        try:
            ingest_file(path, args.norma)
        except Exception as error:
            errors += 1
            print(f"   ❌ {path.name}: {error}", flush=True)

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
