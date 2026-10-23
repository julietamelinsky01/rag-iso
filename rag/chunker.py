"""Divide el documento en fragmentos respetando su estructura.

- Cada sección (según los títulos) es un fragmento; si es muy larga, se
  subdivide con solapamiento.
- Cada fragmento guarda la "ruta" de títulos, por ejemplo:
      Descripción del Proceso > Revisión por la Dirección
- Las tablas grandes van en fragmentos propios, cortadas por filas
  completas (cada fila incluye el nombre de sus columnas). Las tablas
  chicas quedan junto al texto de su sección, para no perder contexto.
- En PDF y texto se detectan cláusulas numeradas: 7.5.3, 8.1, A.5.1...
- Las páginas de índice se omiten: repiten títulos con números de página
  y generarían citas a la página equivocada.
- Las secciones de historial de cambios se marcan con tipo "historial",
  para no confundirlas con lo que el documento pide hoy.
"""
import re
from dataclasses import dataclass

from rag.loaders import Block

CLAUSE_RE = re.compile(
    r"^\s*((?:[A-Z]\.)?\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+([A-ZÁÉÍÓÚÑ][^\n]{2,120})$"
)
HISTORIAL_RE = re.compile(
    r"historial|control de cambios|registro de (?:cambios|revisiones)",
    re.IGNORECASE,
)
# Final típico de una línea de índice: número de página o puntos guía.
TOC_TAIL_RE = re.compile(r"(?:\.{3,}|…+|\s)\s*\d{1,3}\s*$")
DOT_LEADER_RE = re.compile(r"(?:\.{4,}|…{2,})\s*\d{1,3}\s*$")

# Una página es índice si muchas de sus líneas son "cláusula + título + página".
TOC_MIN_LINES = 5
TOC_MIN_RATIO = 0.4

MAX_CHARS = 1800
# Las tablas admiten algo más, para no separar filas de un mismo registro.
MAX_TABLE_CHARS = 2600
OVERLAP = 200
SMALL_TABLE = 400  # caracteres: hasta acá la tabla queda con su sección


@dataclass
class Chunk:
    content: str
    clausula: str | None
    titulo: str | None     # ruta de títulos de la sección
    pagina: int | None
    tipo: str              # "contenido" | "tabla" | "historial"


def chunk_blocks(blocks: list[Block]) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []  # pila de (nivel, título)
    clausula: str | None = None
    buffer: list[str] = []
    buffer_page: int | None = None
    buffer_kinds: set[str] = set()

    def ruta() -> str | None:
        return " > ".join(title for _, title in path) or None

    def tipo(kind: str) -> str:
        if any(HISTORIAL_RE.search(title) for _, title in path):
            return "historial"
        return kind

    def flush() -> None:
        nonlocal buffer, buffer_page, buffer_kinds
        text = _clean("\n".join(buffer))
        if text:
            kind = "tabla" if buffer_kinds == {"table"} else "contenido"
            for piece in _split(text):
                chunks.append(
                    Chunk(piece, clausula, ruta(), buffer_page, tipo(kind))
                )
        buffer, buffer_page, buffer_kinds = [], None, set()

    def push_heading(level: int, title: str) -> None:
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))

    for block in blocks:
        if block.kind == "heading":
            flush()
            push_heading(block.level, block.text)
            clausula = _clause_of(block.text) or (
                clausula if block.level > 1 else None
            )
        elif block.kind == "table":
            if len(block.text) <= SMALL_TABLE:
                buffer.append(block.text)
                buffer_kinds.add("table")
                if buffer_page is None:
                    buffer_page = block.page
                continue
            flush()
            for piece in _split(block.text, by_lines=True):
                chunks.append(
                    Chunk(piece, clausula, ruta(), block.page, tipo("tabla"))
                )
        else:
            if _is_toc_page(block):
                continue
            # En PDF y texto, las cláusulas numeradas vienen dentro del texto.
            for line in block.text.splitlines():
                match = CLAUSE_RE.match(line)
                if match and _looks_like_heading(match.group(2)):
                    flush()
                    clausula = match.group(1)
                    push_heading(
                        10 + clausula.count("."),
                        f"{clausula} {match.group(2).strip()}",
                    )
                if buffer_page is None:
                    buffer_page = block.page
                buffer.append(line)
                if line.strip():
                    buffer_kinds.add("text")
    flush()
    return chunks


def _is_toc_page(block: Block) -> bool:
    if block.page is None:
        return False
    lines = [line for line in block.text.splitlines() if line.strip()]
    toc = sum(
        1 for line in lines
        if CLAUSE_RE.match(line) and TOC_TAIL_RE.search(line)
    )
    return toc >= TOC_MIN_LINES and toc >= TOC_MIN_RATIO * len(lines)


def _clause_of(title: str) -> str | None:
    match = re.match(r"^\s*((?:[A-Z]\.)?\d{1,2}(?:\.\d{1,2}){0,4})\.?\s", title)
    return match.group(1) if match else None


def _looks_like_heading(title: str) -> bool:
    title = title.strip()
    if DOT_LEADER_RE.search(title):
        return False  # línea de índice con puntos guía: "Alcance ....... 7"
    return not title.endswith((".", ",", ";")) and len(title.split()) <= 15


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, by_lines: bool = False) -> list[str]:
    if len(text) <= (MAX_TABLE_CHARS if by_lines else MAX_CHARS):
        return [text]
    if by_lines:  # tablas: agrupar filas completas, sin cortarlas
        # Las filas van separadas por una línea en blanco.
        separator = "\n\n" if "\n\n" in text else "\n"
        parts, current = [], ""
        for row in text.split(separator):
            if current and len(current) + len(row) + len(separator) > MAX_TABLE_CHARS:
                parts.append(current)
                current = row
            else:
                current = f"{current}{separator}{row}" if current else row
        if current:
            parts.append(current)
        return parts
    parts, start = [], 0
    while start < len(text):
        end = min(start + MAX_CHARS, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if cut > start + MAX_CHARS // 2:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - OVERLAP
    return parts
