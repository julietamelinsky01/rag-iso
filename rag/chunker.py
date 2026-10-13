"""Corta el texto en fragmentos respetando la estructura de cláusulas ISO.

Detecta encabezados como:
    7.5.3 Control de la información documentada
    8 Operación
    A.5.1 Políticas para la seguridad de la información   (anexos)
Si una cláusula es muy larga, la sub-divide por tamaño con solapamiento.
"""
import re
from dataclasses import dataclass

# Encabezado de cláusula: número tipo 7 / 7.5 / 7.5.3 / A.5.1, seguido de un título
# que empieza con mayúscula. Limita la longitud para no confundir con texto normal.
HEADING_RE = re.compile(
    r"^\s*((?:[A-Z]\.)?\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+([A-ZÁÉÍÓÚÑ][^\n]{2,120})$"
)

MAX_CHARS = 1800
OVERLAP = 200


@dataclass
class Chunk:
    content: str
    clausula: str | None
    titulo: str | None
    pagina: int


def chunk_pages(pages: list[tuple[int, str]]) -> list[Chunk]:
    sections: list[dict] = []
    current = {"clausula": None, "titulo": None, "pagina": pages[0][0] if pages else 1, "lines": []}

    for page_num, text in pages:
        for line in text.splitlines():
            m = HEADING_RE.match(line)
            if m and _looks_like_heading(m.group(2)):
                if any(l.strip() for l in current["lines"]):
                    sections.append(current)
                current = {
                    "clausula": m.group(1),
                    "titulo": m.group(2).strip(),
                    "pagina": page_num,
                    "lines": [line],
                }
            else:
                current["lines"].append(line)
    if any(l.strip() for l in current["lines"]):
        sections.append(current)

    chunks: list[Chunk] = []
    for s in sections:
        text = _clean("\n".join(s["lines"]))
        if len(text) < 30 and chunks:
            continue  # encabezado suelto sin contenido
        for piece in _split_long(text):
            chunks.append(Chunk(piece, s["clausula"], s["titulo"], s["pagina"]))
    return chunks


def _looks_like_heading(title: str) -> bool:
    # Evita falsos positivos: líneas que terminan en punto suelen ser oraciones
    t = title.strip()
    return not t.endswith((".", ",", ";")) and len(t.split()) <= 15


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + MAX_CHARS, len(text))
        # intentar cortar en un salto de párrafo o fin de oración
        if end < len(text):
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if cut > start + MAX_CHARS // 2:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - OVERLAP
    return parts
