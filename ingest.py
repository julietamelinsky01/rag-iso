"""Prepara documentos para el RAG y carga archivos locales.

Uso:
    python ingest.py docs/PRO-02.docx --revisar   (muestra la división, no carga)
    python ingest.py docs/PRO-02.docx
    python ingest.py docs/
    python ingest.py docs/ISO_9001.pdf --norma "ISO 9001:2015"

prepare_file() lee el documento (texto, títulos, tablas y encabezado),
lo divide en fragmentos y genera embeddings validados; también la usa
sync_drive.py. La carga local reemplaza el documento de forma atómica
con public.replace_document y lo deja activo.

Los documentos administrados desde Drive se actualizan con sync_drive.py,
no con este script.
"""
import argparse
import math
from pathlib import Path

from rag.chunker import Chunk, chunk_blocks
from rag.clients import embed, supabase
from rag.loaders import DocMeta, load_document

EXTS = {".pdf", ".docx", ".txt", ".md"}
EMBEDDING_DIM = 768

# Subir este número cuando cambie la forma de leer o fragmentar:
# sync_drive.py vuelve a procesar los archivos hechos con otra versión.
PIPELINE_VERSION = 4


def read_file(path: Path) -> tuple[DocMeta, list[Chunk]]:
    """Lee y fragmenta, sin generar embeddings."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo: {path}")
    if path.suffix.lower() not in EXTS:
        raise ValueError(f"Formato no admitido: {path.suffix}")

    meta, blocks = load_document(str(path))
    chunks = chunk_blocks(blocks)
    card = header_card(meta)
    if chunks and card:
        chunks.insert(0, card)
    if not chunks:
        raise ValueError(
            "No se extrajo texto. Revisá si el documento necesita OCR."
        )
    for index, chunk in enumerate(chunks):
        if not chunk.content or not chunk.content.strip():
            raise ValueError(f"El fragmento {index} no tiene texto.")
    return meta, chunks


def header_card(meta: DocMeta) -> Chunk | None:
    """Ficha con los datos del encabezado, para que también se puedan buscar
    (por ejemplo, quién aprobó el procedimiento)."""
    if not meta.codigo:
        return None
    lines = [f"Documento: {' '.join(p for p in (meta.codigo, meta.titulo) if p)}"]
    if meta.revision:
        revision = f"Revisión: {meta.revision}"
        if meta.fecha_revision:
            revision += f" del {meta.fecha_revision}"
        lines.append(revision)
    if meta.emision:
        lines.append(f"Fecha de emisión: {meta.emision}")
    if meta.realizado:
        lines.append(f"Realizado por: {meta.realizado}")
    if meta.aprobado:
        lines.append(f"Aprobado por: {meta.aprobado}")
    # Sin esta línea, el modelo deducía que la revisión cargada es la vigente.
    lines.append(
        "Vigencia: el documento no indica si esta revisión es la vigente."
    )
    return Chunk("\n".join(lines), None, "Ficha del documento", None, "contenido")


def embedding_text(meta: DocMeta, label: str, chunk: Chunk) -> str:
    """Texto que se vectoriza: documento y sección dan contexto."""
    head = meta.label() if meta.codigo else label
    if chunk.titulo:
        head += f" | {chunk.titulo}"
    if chunk.tipo == "historial":
        head += " | historial de cambios"
    return f"{head}\n{chunk.content}"


def prepare_file(path: Path, label: str | None = None) -> tuple[dict, list[dict]]:
    """Devuelve (datos del documento, fragmentos listos para guardar).

    label es el nombre a mostrar (por ejemplo, el nombre en Drive).
    """
    path = Path(path)
    label = label or path.name
    print(f"\n📄 {label}", flush=True)

    meta, chunks = read_file(path)
    print(
        f"   {_summary(meta, chunks)}",
        flush=True,
    )

    print("   Generando embeddings...", flush=True)
    vectors = embed([embedding_text(meta, label, chunk) for chunk in chunks])

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
                "tipo": chunk.tipo,
                "content": chunk.content,
                "embedding": values,
            }
        )

    return meta.as_dict(), rows


def _summary(meta: DocMeta, chunks: list[Chunk]) -> str:
    clausulas = sum(1 for chunk in chunks if chunk.clausula)
    tablas = sum(1 for chunk in chunks if chunk.tipo == "tabla")
    historial = sum(1 for chunk in chunks if chunk.tipo == "historial")
    text = f"{len(chunks)} fragmentos"
    details = [
        f"{clausulas} con cláusula" if clausulas else "",
        f"{tablas} de tabla" if tablas else "",
        f"{historial} de historial" if historial else "",
    ]
    details = [detail for detail in details if detail]
    if details:
        text += f" ({', '.join(details)})"
    if meta.codigo:
        text = f"{meta.label()} → {text}"
    return text


def preview(path: Path) -> None:
    """Muestra cómo queda dividido el documento, sin cargar nada."""
    meta, chunks = read_file(path)
    print(f"\n📄 {path.name}")
    if meta.codigo:
        print(f"   Documento: {meta.label()} · emisión: {meta.emision or '-'}")
        print(
            f"   Realizado por: {meta.realizado or '-'} · "
            f"Aprobado por: {meta.aprobado or '-'}"
        )
    print(f"   {_summary(meta, chunks)}\n")
    for index, chunk in enumerate(chunks):
        where = chunk.titulo or "(inicio del documento)"
        if chunk.clausula and chunk.clausula not in where:
            where = f"cláusula {chunk.clausula} · {where}"
        page = f" · pág. {chunk.pagina}" if chunk.pagina else ""
        print(
            f"--- #{index} [{chunk.tipo}] {where}{page} · "
            f"{len(chunk.content)} caracteres"
        )
        print(chunk.content)
        print()


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

    doc_meta, rows = prepare_file(path)

    print("   Guardando documento en Supabase...", flush=True)

    # Una única llamada: la función SQL reemplaza todos los fragmentos
    # en una transacción. Si falla, se conserva la versión anterior.
    result = db.rpc(
        "replace_document",
        {
            "p_source": path.name,
            "p_title": path.stem,
            "p_norma": norma,
            "p_doc_meta": doc_meta,
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
    parser.add_argument(
        "--revisar",
        action="store_true",
        help="Solo mostrar cómo se divide cada documento, sin cargar nada",
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
            if path.is_file()
            and path.suffix.lower() in EXTS
            and not path.name.startswith("~$")  # temporales de Word
        )
    )

    if not files:
        print("No encontré documentos para cargar.")
        return

    errors = 0
    for path in files:
        try:
            if args.revisar:
                preview(path)
            else:
                ingest_file(path, args.norma)
        except Exception as error:
            errors += 1
            print(f"   ❌ {path.name}: {error}", flush=True)

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
