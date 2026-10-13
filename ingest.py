"""Carga uno o más documentos en Supabase.

Uso:
    python ingest.py docs/ISO_9001.pdf
    python ingest.py docs/            (carga todos los PDF/DOCX/TXT de la carpeta)
    python ingest.py docs/ISO_9001.pdf --norma "ISO 9001:2015"

Si el documento ya estaba cargado, lo reemplaza (borra sus fragmentos viejos).
"""
import argparse
from pathlib import Path

from rag.chunker import chunk_pages
from rag.clients import embed, supabase
from rag.loaders import load_document

EXTS = {".pdf", ".docx", ".txt", ".md"}


def ingest_file(path: Path, norma: str | None = None) -> None:
    print(f"\n📄 {path.name}")
    pages = load_document(str(path))
    chunks = chunk_pages(pages)
    clausulas = sum(1 for c in chunks if c.clausula)
    print(f"   {len(pages)} página(s) → {len(chunks)} fragmentos ({clausulas} con cláusula detectada)")

    # El texto que se vectoriza incluye cláusula y título para dar contexto
    texts = [
        f"{c.clausula or ''} {c.titulo or ''}\n{c.content}".strip() for c in chunks
    ]
    vectors = embed(texts)
    if not chunks:
        raise RuntimeError("No se extrajo texto. Revisá si el documento necesita OCR.")

    db = supabase()
    # upsert del documento (si existía, se borran sus chunks por la FK en cascada)
    db.table("documents").delete().eq("source", path.name).execute()
    doc = (
        db.table("documents")
        .insert({"source": path.name, "title": path.stem, "norma": norma})
        .execute()
        .data[0]
    )


    rows = [
        {
            "document_id": doc["id"],
            "chunk_index": i,
            "clausula": c.clausula,
            "titulo": c.titulo,
            "pagina": c.pagina,
            "content": c.content,
            "embedding": v,
        }
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]
    for i in range(0, len(rows), 200):
        db.table("chunks").insert(rows[i : i + 200]).execute()
    print("   ✅ cargado")


def main() -> None:
    ap = argparse.ArgumentParser(description="Cargar documentos al RAG")
    ap.add_argument("ruta", help="archivo o carpeta")
    ap.add_argument("--norma", help='nombre de la norma, ej: "ISO 9001:2015"')
    args = ap.parse_args()

    ruta = Path(args.ruta)
    files = [ruta] if ruta.is_file() else sorted(p for p in ruta.rglob("*") if p.suffix.lower() in EXTS)
    if not files:
        print("No encontré documentos para cargar.")
        return
    for f in files:
        try:
            ingest_file(f, args.norma)
        except Exception as e:  # seguir con los demás archivos
            print(f"   ❌ error: {e}")


if __name__ == "__main__":
    main()
