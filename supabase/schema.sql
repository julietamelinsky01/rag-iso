-- =============================================================
-- RAG de normas ISO - esquema para Supabase (Postgres + pgvector)
-- Ejecutar una sola vez en: Supabase > SQL Editor > New query
-- =============================================================

-- 1) Extensión de vectores
create extension if not exists vector;

-- 2) Documentos originales (una fila por archivo)
create table if not exists documents (
  id          bigserial primary key,
  source      text not null unique,      -- nombre de archivo o ID de Drive
  title       text,
  norma       text,                      -- ej: "ISO 9001:2015" (opcional)
  created_at  timestamptz default now()
);

-- 3) Fragmentos (chunks) con su embedding
--    1536 dimensiones = OpenAI text-embedding-3-small.
--    Si cambiás de modelo de embeddings, cambiá este número y re-indexá todo.
create table if not exists chunks (
  id           bigserial primary key,
  document_id  bigint references documents(id) on delete cascade,
  chunk_index  int not null,
  clausula     text,                     -- ej: "7.5.3" si se detectó
  titulo       text,                     -- título de la cláusula
  pagina       int,
  content      text not null,
  embedding    vector(1536),
  fts          tsvector generated always as (to_tsvector('spanish', coalesce(clausula,'') || ' ' || coalesce(titulo,'') || ' ' || content)) stored
);

-- 4) Índices: vectorial (HNSW, coseno) y de texto completo
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_fts_idx on chunks using gin (fts);
create index if not exists chunks_clausula_idx on chunks (clausula);

-- 5) Búsqueda HÍBRIDA: combina similitud semántica + coincidencia de palabras
--    (útil para preguntas con números de cláusula como "7.5.3")
--    usando Reciprocal Rank Fusion (RRF).
create or replace function hybrid_search(
  query_text       text,
  query_embedding  vector(1536),
  match_count      int default 6,
  rrf_k            int default 50
)
returns table (
  id bigint, document_id bigint, source text, clausula text, titulo text,
  pagina int, content text, score float
)
language sql stable
as $$
  with semantic as (
    select c.id, row_number() over (order by c.embedding <=> query_embedding) as rank
    from chunks c
    order by c.embedding <=> query_embedding
    limit match_count * 3
  ),
  keyword as (
    select c.id, row_number() over (order by ts_rank_cd(c.fts, q) desc) as rank
    from chunks c, websearch_to_tsquery('spanish', query_text) q
    where c.fts @@ q
    order by ts_rank_cd(c.fts, q) desc
    limit match_count * 3
  ),
  fused as (
    select coalesce(s.id, k.id) as id,
           coalesce(1.0 / (rrf_k + s.rank), 0) + coalesce(1.0 / (rrf_k + k.rank), 0) as score
    from semantic s full outer join keyword k on s.id = k.id
  )
  select c.id, c.document_id, d.source, c.clausula, c.titulo, c.pagina, c.content, f.score
  from fused f
  join chunks c on c.id = f.id
  join documents d on d.id = c.document_id
  order by f.score desc
  limit match_count;
$$;

-- 6) Seguridad: activar RLS. Los scripts usan la service_role key (que la saltea);
--    los usuarios finales no acceden directo a estas tablas.
alter table documents enable row level security;
alter table chunks enable row level security;
