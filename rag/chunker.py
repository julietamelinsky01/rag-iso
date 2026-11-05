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
from itertools import groupby

from rag.loaders import Block

CLAUSE_RE = re.compile(
    r"^\s*((?:[A-Z]\.)?\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+([A-ZÁÉÍÓÚÑ][^\n]{2,120})$"
)
# Artículos de leyes: "ARTICULO 1° — (Objeto).", "Art. 44. — El contrato...".
# Exige puntuación después del número, para no tomar citas como
# "Art. 5 de la ley" que quedaron al comienzo de un renglón.
ARTICLE_RE = re.compile(
    r"^\s*(?:ART[IÍ]CULO|Art[ií]culo|Art\.)\s*(\d{1,3})(?:\s*(?:bis|ter))?\s*[°º]?"
    r"\s*[.\-‐—–(]"
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

MAX_TOP_CLAUSE_WORDS = 6  # "10. Conclusiones" sí; "3. Los datos deben ser..." no
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
    has_articles = False
    buffer: list[tuple[str, int | None]] = []  # (renglón, página)
    buffer_kinds: set[str] = set()

    def ruta() -> str | None:
        return " > ".join(title for _, title in path) or None

    def tipo(kind: str) -> str:
        if any(HISTORIAL_RE.search(title) for _, title in path):
            return "historial"
        return kind

    def flush() -> None:
        nonlocal buffer, buffer_kinds
        text, page_starts = _join_pages(buffer)
        if text:
            kind = "tabla" if buffer_kinds == {"table"} else "contenido"
            cursor = 0
            for piece in _split(text):
                position = max(text.find(piece, cursor), cursor)
                chunks.append(
                    Chunk(piece, clausula, ruta(),
                          _page_at(page_starts, position), tipo(kind))
                )
                cursor = position + 1
        buffer, buffer_kinds = [], set()

    def push_heading(level: int, title: str) -> None:
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))

    for block in blocks:
        if block.kind == "heading":
            flush()
            push_heading(block.level, block.text)
            # Un título sin número cierra la cláusula anterior: si no, su
            # número se arrastra a secciones que no le corresponden.
            clausula = _clause_of(block.text)
        elif block.kind == "table":
            if len(block.text) <= SMALL_TABLE:
                buffer.append((block.text, block.page))
                buffer_kinds.add("table")
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
                article = ARTICLE_RE.match(line)
                match = CLAUSE_RE.match(line)
                if article:
                    flush()
                    has_articles = True
                    clausula = f"Art. {article.group(1)}"
                    push_heading(10, clausula)
                elif (match and not has_articles
                        and _looks_like_clause(match.group(1), match.group(2))):
                    flush()
                    clausula = match.group(1)
                    push_heading(
                        10 + clausula.count("."),
                        f"{clausula} {match.group(2).strip()}",
                    )
                buffer.append((line, block.page))
                if line.strip():
                    buffer_kinds.add("text")
    flush()
    return chunks


def _join_pages(
    lines: list[tuple[str, int | None]]
) -> tuple[str, list[tuple[int, int | None]]]:
    """Une los renglones y registra en qué posición empieza cada página."""
    text, page_starts = "", []
    for page, group in groupby(lines, key=lambda line: line[1]):
        segment = _clean("\n".join(line for line, _ in group))
        if segment:
            if text:
                text += "\n"
            page_starts.append((len(text), page))
            text += segment
    return text, page_starts


def _page_at(
    page_starts: list[tuple[int, int | None]], position: int
) -> int | None:
    """Página en la que empieza el texto de esa posición."""
    current = page_starts[0][1]
    for start, page in page_starts:
        if start > position:
            break
        current = page
    return current


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


def _looks_like_clause(number: str, title: str) -> bool:
    """Un número suelto ("3") con mucho texto es un ítem de lista, no una cláusula."""
    if "." not in number and len(title.split()) > MAX_TOP_CLAUSE_WORDS:
        return False
    return _looks_like_heading(title)


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
