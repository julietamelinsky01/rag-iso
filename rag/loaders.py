"""Lectura de documentos: devuelve una lista de (numero_de_pagina, texto)."""
from pathlib import Path


def load_document(path: str) -> list[tuple[int, str]]:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext == ".docx":
        return _load_docx(path)
    if ext in (".txt", ".md"):
        return [(1, Path(path).read_text(encoding="utf-8", errors="ignore"))]
    raise ValueError(f"Formato no soportado todavía: {ext} (usá PDF, DOCX, TXT o MD)")


def _load_pdf(path: str) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i, text))
    if not pages:
        raise ValueError(
            "El PDF no tiene texto extraíble (¿es escaneado?). Hace falta OCR, "
            "por ejemplo con Docling."
        )
    return pages


def _load_docx(path: str) -> list[tuple[int, str]]:
    from docx import Document

    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    # Word no tiene páginas fijas: todo va como "página 1"
    return [(1, text)]
