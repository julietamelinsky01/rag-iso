-- Sincronización integrada de Drive.
-- Ejecutar una vez, después de 002, 003 y 004.
--
-- Cambia la identidad de los documentos de Drive al ID del archivo,
-- usa la huella MD5 para decidir si hay que regenerar embeddings y
-- desactiva (sin borrar) los documentos que salen de la carpeta.
--
-- Flujo:
--   1. stage_drive_chunks: sube por lotes los fragmentos de UN documento
--      a una zona de preparación. No afecta las búsquedas.
--   2. reconcile_drive_folder: en una sola transacción aplica los
--      documentos listos, actualiza metadatos y desactiva los retirados.

begin;

-- ---------------------------------------------------------------
-- 1) Columnas y tablas
-- ---------------------------------------------------------------

alter table public.documents
  add column if not exists active boolean not null default true;

alter table public.drive_sync_state
  add column if not exists content_md5 text;

-- Evita que dos sincronizaciones confirmen sobre el mismo estado.
create table if not exists public.drive_sync_control (
  folder_id text primary key,
  generation bigint not null default 0
);

-- Contenido preparado y todavía no confirmado.
-- Permite reintentar sin regenerar embeddings ya calculados.
create table if not exists public.drive_staged_documents (
  folder_id text not null,
  file_id text not null,
  content_md5 text not null,
  chunk_total integer not null check (chunk_total > 0),
  created_at timestamptz not null default now(),
  primary key (folder_id, file_id, content_md5)
);

create table if not exists public.drive_staged_chunks (
  folder_id text not null,
  file_id text not null,
  content_md5 text not null,
  chunk_index integer not null,
  clausula text,
  titulo text,
  pagina integer,
  content text not null,
  embedding vector(768) not null,
  primary key (folder_id, file_id, content_md5, chunk_index),
  foreign key (folder_id, file_id, content_md5)
    references public.drive_staged_documents (folder_id, file_id, content_md5)
    on delete cascade
);

alter table public.drive_sync_control enable row level security;
alter table public.drive_staged_documents enable row level security;
alter table public.drive_staged_chunks enable row level security;

revoke all on public.drive_sync_control from public, anon, authenticated;
revoke all on public.drive_staged_documents from public, anon, authenticated;
revoke all on public.drive_staged_chunks from public, anon, authenticated;

grant select, insert, update on public.drive_sync_control to service_role;
grant select, insert, update, delete
  on public.drive_staged_documents, public.drive_staged_chunks
  to service_role;

-- ---------------------------------------------------------------
-- 2) Preparación por lotes de un documento
-- ---------------------------------------------------------------

create or replace function public.stage_drive_chunks(
  p_folder_id text,
  p_file_id text,
  p_md5 text,
  p_total integer,
  p_chunks jsonb
)
returns integer
language plpgsql
security invoker
set search_path = public, extensions, pg_temp
as $$
declare
  v_total integer;
  v_count integer;
begin
  if nullif(btrim(p_folder_id), '') is null
     or nullif(btrim(p_file_id), '') is null
     or nullif(btrim(p_md5), '') is null then
    raise exception 'Faltan carpeta, archivo o huella.';
  end if;

  if p_total is null or p_total < 1 then
    raise exception 'Cantidad total de fragmentos inválida.';
  end if;

  if p_chunks is null
     or jsonb_typeof(p_chunks) <> 'array'
     or jsonb_array_length(p_chunks) = 0 then
    raise exception 'El lote de fragmentos está vacío o no es una lista.';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_chunks) as batch(item)
    where jsonb_typeof(batch.item -> 'chunk_index') is distinct from 'number'
       or (batch.item ->> 'chunk_index')::integer not between 0 and p_total - 1
       or nullif(btrim(batch.item ->> 'content'), '') is null
       or jsonb_typeof(batch.item -> 'embedding') is distinct from 'array'
  ) then
    raise exception 'Hay fragmentos sin índice válido, sin texto o sin embedding.';
  end if;

  -- Solo se conserva la preparación de la versión actual del archivo.
  delete from public.drive_staged_documents
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 <> p_md5;

  select chunk_total into v_total
  from public.drive_staged_documents
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 = p_md5
  for update;

  -- Si cambió la fragmentación, se descarta la preparación anterior.
  if found and v_total <> p_total then
    delete from public.drive_staged_documents
    where folder_id = p_folder_id
      and file_id = p_file_id
      and content_md5 = p_md5;
  end if;

  insert into public.drive_staged_documents (folder_id, file_id, content_md5, chunk_total)
  values (p_folder_id, p_file_id, p_md5, p_total)
  on conflict (folder_id, file_id, content_md5) do nothing;

  insert into public.drive_staged_chunks (
    folder_id, file_id, content_md5, chunk_index,
    clausula, titulo, pagina, content, embedding
  )
  select
    p_folder_id,
    p_file_id,
    p_md5,
    (batch.item ->> 'chunk_index')::integer,
    batch.item ->> 'clausula',
    batch.item ->> 'titulo',
    (batch.item ->> 'pagina')::integer,
    batch.item ->> 'content',
    (batch.item ->> 'embedding')::vector(768)
  from jsonb_array_elements(p_chunks) as batch(item)
  on conflict (folder_id, file_id, content_md5, chunk_index) do update
    set clausula = excluded.clausula,
        titulo = excluded.titulo,
        pagina = excluded.pagina,
        content = excluded.content,
        embedding = excluded.embedding;

  select count(*) into v_count
  from public.drive_staged_chunks
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 = p_md5;

  return v_count;
end;
$$;

revoke all on function public.stage_drive_chunks(text, text, text, integer, jsonb)
from public, anon, authenticated;
grant execute on function public.stage_drive_chunks(text, text, text, integer, jsonb)
to service_role;

-- ---------------------------------------------------------------
-- 3) Confirmación de la carpeta en una transacción
-- ---------------------------------------------------------------
-- p_present: IDs de todos los archivos compatibles que siguen en la
--            carpeta, incluidos los que fallaron o se postergaron.
--            Los que no están se desactivan.
-- p_apply:   archivos listos para aplicar: [{id, name, md5,
--            modifiedTime, version}]. Su contenido sale de la
--            preparación o, si la huella no cambió, se reutiliza.

-- Versión de una sola lista incluida en una entrega anterior.
drop function if exists public.reconcile_drive_folder(text, bigint, jsonb);

create or replace function public.reconcile_drive_folder(
  p_folder_id text,
  p_expected_generation bigint,
  p_present jsonb,
  p_apply jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = public, extensions, pg_temp
as $$
declare
  v_generation bigint;
  v_file jsonb;
  v_state public.drive_sync_state%rowtype;
  v_has_state boolean;
  v_doc_id bigint;
  v_source text;
  v_total integer;
  v_staged integer;
  v_applied integer := 0;
  v_content integer := 0;
  v_disabled integer := 0;
begin
  if nullif(btrim(p_folder_id), '') is null then
    raise exception 'Falta la carpeta.';
  end if;

  if jsonb_typeof(p_present) is distinct from 'array'
     or jsonb_typeof(p_apply) is distinct from 'array' then
    raise exception 'Los listados deben ser listas.';
  end if;

  if exists (
    select 1 from jsonb_array_elements(p_present) as present(item)
    where jsonb_typeof(present.item) <> 'string'
       or nullif(btrim(present.item #>> '{}'), '') is null
  ) then
    raise exception 'El listado de archivos presentes no es válido.';
  end if;

  if exists (
    select 1 from jsonb_array_elements_text(p_present) as present(file_id)
    group by present.file_id having count(*) > 1
  ) or exists (
    select 1 from jsonb_array_elements(p_apply) as apply(item)
    group by apply.item ->> 'id' having count(*) > 1
  ) then
    raise exception 'Hay IDs repetidos en los listados.';
  end if;

  if exists (
    select 1 from jsonb_array_elements(p_apply) as apply(item)
    where not (p_present ? (apply.item ->> 'id'))
  ) then
    raise exception 'Un archivo a aplicar no figura entre los presentes.';
  end if;

  insert into public.drive_sync_control (folder_id)
  values (p_folder_id)
  on conflict (folder_id) do nothing;

  select generation into v_generation
  from public.drive_sync_control
  where folder_id = p_folder_id
  for update;

  if v_generation <> p_expected_generation then
    raise exception 'Otra sincronización cambió la carpeta. Ejecutá nuevamente.';
  end if;

  for v_file in
    select apply.item from jsonb_array_elements(p_apply) as apply(item)
  loop
    if nullif(v_file ->> 'id', '') is null
       or nullif(v_file ->> 'name', '') is null
       or nullif(v_file ->> 'md5', '') is null
       or nullif(v_file ->> 'modifiedTime', '') is null then
      raise exception 'Metadatos incompletos en un archivo a aplicar.';
    end if;

    select * into v_state
    from public.drive_sync_state
    where folder_id = p_folder_id
      and file_id = v_file ->> 'id'
    for update;
    v_has_state := found;

    v_source := 'drive:' || p_folder_id || ':' || (v_file ->> 'id');

    if v_has_state then
      -- Conserva el ID del documento ya vinculado (y su norma).
      v_doc_id := v_state.document_id;
      update public.documents
      set source = v_source,
          title = v_file ->> 'name',
          active = true
      where id = v_doc_id;
    else
      insert into public.documents (source, title, active)
      values (v_source, v_file ->> 'name', true)
      on conflict (source) do update
        set title = excluded.title,
            active = true
      returning id into v_doc_id;
    end if;

    if v_has_state
       and v_state.content_md5 = v_file ->> 'md5'
       and exists (select 1 from public.chunks where document_id = v_doc_id) then
      -- Mismo contenido: solo cambian metadatos o actividad.
      null;
    else
      select chunk_total into v_total
      from public.drive_staged_documents
      where folder_id = p_folder_id
        and file_id = v_file ->> 'id'
        and content_md5 = v_file ->> 'md5';

      if not found then
        raise exception 'Falta el contenido preparado de %.', v_file ->> 'name';
      end if;

      select count(*) into v_staged
      from public.drive_staged_chunks
      where folder_id = p_folder_id
        and file_id = v_file ->> 'id'
        and content_md5 = v_file ->> 'md5';

      if v_staged <> v_total then
        raise exception 'La preparación de % está incompleta (% de %).',
          v_file ->> 'name', v_staged, v_total;
      end if;

      delete from public.chunks where document_id = v_doc_id;

      insert into public.chunks (
        document_id, chunk_index, clausula, titulo, pagina, content, embedding
      )
      select v_doc_id, staged.chunk_index, staged.clausula, staged.titulo,
             staged.pagina, staged.content, staged.embedding
      from public.drive_staged_chunks as staged
      where staged.folder_id = p_folder_id
        and staged.file_id = v_file ->> 'id'
        and staged.content_md5 = v_file ->> 'md5'
      order by staged.chunk_index;

      v_content := v_content + 1;
    end if;

    -- La preparación ya no hace falta para este archivo.
    delete from public.drive_staged_documents
    where folder_id = p_folder_id
      and file_id = v_file ->> 'id';

    insert into public.drive_sync_state (
      folder_id, file_id, file_name, modified_time, drive_version,
      document_id, content_md5, synced_at
    )
    values (
      p_folder_id, v_file ->> 'id', v_file ->> 'name', v_file ->> 'modifiedTime',
      v_file ->> 'version', v_doc_id, v_file ->> 'md5', now()
    )
    on conflict (folder_id, file_id) do update
      set file_name = excluded.file_name,
          modified_time = excluded.modified_time,
          drive_version = excluded.drive_version,
          document_id = excluded.document_id,
          content_md5 = excluded.content_md5,
          synced_at = excluded.synced_at;

    v_applied := v_applied + 1;
  end loop;

  -- Retirados: se conservan los datos, pero salen de la búsqueda.
  update public.documents as doc
  set active = false
  where doc.active
    and exists (
      select 1 from public.drive_sync_state as state
      where state.folder_id = p_folder_id
        and state.document_id = doc.id
        and not (p_present ? state.file_id)
    );
  get diagnostics v_disabled = row_count;

  -- Preparaciones de archivos que ya no están en la carpeta.
  delete from public.drive_staged_documents as staged
  where staged.folder_id = p_folder_id
    and not (p_present ? staged.file_id);

  update public.drive_sync_control
  set generation = generation + 1
  where folder_id = p_folder_id;

  return jsonb_build_object(
    'aplicados', v_applied,
    'contenido_nuevo', v_content,
    'desactivados', v_disabled
  );
end;
$$;

revoke all on function public.reconcile_drive_folder(text, bigint, jsonb, jsonb)
from public, anon, authenticated;
grant execute on function public.reconcile_drive_folder(text, bigint, jsonb, jsonb)
to service_role;

-- ---------------------------------------------------------------
-- 4) Carga local: volver a cargar un documento lo reactiva
-- ---------------------------------------------------------------

create or replace function public.replace_document(
  p_source text,
  p_title text,
  p_norma text,
  p_chunks jsonb
)
returns bigint
language plpgsql
security invoker
set search_path = public, extensions, pg_temp
as $$
declare
  v_document_id bigint;
begin
  if p_source is null or btrim(p_source) = '' then
    raise exception 'El documento necesita un identificador.';
  end if;

  if p_chunks is null
     or jsonb_typeof(p_chunks) <> 'array' then
    raise exception 'Los fragmentos deben ser una lista.';
  end if;

  if jsonb_array_length(p_chunks) = 0 then
    raise exception 'No se puede cargar un documento sin fragmentos.';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_chunks) as items(item)
    where nullif(btrim(item->>'content'), '') is null
       or item->>'embedding' is null
       or item->>'embedding' = 'null'
  ) then
    raise exception 'Hay fragmentos sin texto o sin embedding.';
  end if;

  insert into public.documents (source, title, norma, active)
  values (p_source, p_title, p_norma, true)
  on conflict (source) do update
    set title = excluded.title,
        norma = excluded.norma,
        active = true
  returning id into v_document_id;

  delete from public.chunks
  where document_id = v_document_id;

  insert into public.chunks (
    document_id,
    chunk_index,
    clausula,
    titulo,
    pagina,
    content,
    embedding
  )
  select
    v_document_id,
    (items.position - 1)::integer,
    items.item->>'clausula',
    items.item->>'titulo',
    (items.item->>'pagina')::integer,
    items.item->>'content',
    (items.item->>'embedding')::vector(768)
  from jsonb_array_elements(p_chunks)
       with ordinality as items(item, position);

  return v_document_id;
end;
$$;

revoke all on function public.replace_document(text, text, text, jsonb)
from public, anon, authenticated;
grant execute on function public.replace_document(text, text, text, jsonb)
to service_role;

-- ---------------------------------------------------------------
-- 5) Búsqueda: solo documentos activos, con el nombre legible
-- ---------------------------------------------------------------

create or replace function public.hybrid_search(
  query_text text,
  query_embedding vector,
  match_count integer default 6,
  rrf_k integer default 50
)
returns table (
  id bigint,
  document_id bigint,
  source text,
  clausula text,
  titulo text,
  pagina integer,
  content text,
  score double precision
)
language sql
stable
set search_path = public, extensions, pg_temp
as $$
  with semantic as (
    select c.id,
           row_number() over (order by c.embedding <=> query_embedding) as rank
    from public.chunks c
    join public.documents d on d.id = c.document_id
    where d.active and c.embedding is not null
    order by c.embedding <=> query_embedding
    limit match_count * 3
  ),
  keyword as (
    select c.id,
           row_number() over (order by ts_rank_cd(c.fts, q) desc) as rank
    from public.chunks c
    join public.documents d on d.id = c.document_id
    cross join websearch_to_tsquery('spanish', query_text) as q
    where d.active and c.fts @@ q
    order by ts_rank_cd(c.fts, q) desc
    limit match_count * 3
  ),
  fused as (
    select coalesce(s.id, k.id) as id,
           coalesce(1.0 / (rrf_k + s.rank), 0)
           + coalesce(1.0 / (rrf_k + k.rank), 0) as score
    from semantic s
    full outer join keyword k on s.id = k.id
  )
  select c.id,
         c.document_id,
         coalesce(
           (select min(ds.file_name)
            from public.drive_sync_state ds
            where ds.document_id = d.id),
           d.source
         ) as source,
         c.clausula,
         c.titulo,
         c.pagina,
         c.content,
         f.score::double precision
  from fused f
  join public.chunks c on c.id = f.id
  join public.documents d on d.id = c.document_id
  where d.active
  order by f.score desc
  limit match_count;
$$;

-- ---------------------------------------------------------------
-- 6) Retiro del documento de prueba con reglas distintas
-- ---------------------------------------------------------------
-- Se desactiva (no se borra). Para revertir:
--   update public.documents set active = true where source = 'prueba.txt';

update public.documents
set active = false
where source = 'prueba.txt'
  and not exists (
    select 1 from public.drive_sync_state s where s.document_id = documents.id
  );

notify pgrst, 'reload schema';

commit;
