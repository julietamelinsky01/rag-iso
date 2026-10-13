# RAG de normas ISO (Supabase + pgvector)

Primer RAG propio: carga documentos (PDF, DOCX, TXT), los corta por cláusula ISO,
los guarda como vectores en Supabase y responde preguntas citando documento,
cláusula y página.

```
documento → texto → fragmentos por cláusula → embeddings → Supabase (pgvector)
pregunta  → embedding → búsqueda híbrida (semántica + palabras) → LLM → respuesta con citas
```

## 1. Crear el proyecto en Supabase
1. Entrá a https://supabase.com y creá un proyecto nuevo.
2. Andá a **SQL Editor → New query**, pegá el contenido de `supabase/schema.sql` y ejecutalo.
3. En **Project Settings → API** copiá la `Project URL` y la `service_role` key.

## 2. Instalar
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # y completá las claves
```

## 3. Cargar documentos
```bash
python ingest.py docs/mi_norma.pdf --norma "ISO 9001:2015"
python ingest.py docs/           # carga toda la carpeta
```
Volver a cargar el mismo archivo lo reemplaza.

## 4. Preguntar
```bash
python ask.py                                    # modo chat
python ask.py "¿Qué pide la cláusula 7.5.3?"
```

## 5. API (opcional)
```bash
uvicorn api:app --reload
# POST http://localhost:8000/preguntar  {"pregunta": "..."}
```

## Estructura
| Archivo | Qué hace |
|---|---|
| `supabase/schema.sql` | Tablas, índices y la función `hybrid_search` |
| `rag/loaders.py` | Lee PDF / DOCX / TXT |
| `rag/chunker.py` | Corta por cláusula (4.1, 7.5.3, A.5.1…) |
| `rag/clients.py` | Conexión a Supabase y embeddings de OpenAI |
| `rag/answer.py` | Búsqueda + prompt + respuesta con citas |
| `ingest.py` / `ask.py` / `api.py` | Cargar, preguntar por terminal, API HTTP |

## Próximos pasos
- Sincronizar automáticamente la carpeta de Google Drive.
- Docling para PDFs escaneados y tablas complejas.
- Interfaz web (Open WebUI o propia) y Docker.
- Set de preguntas de prueba para medir calidad.
