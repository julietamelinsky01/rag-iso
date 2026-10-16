-- Estructura documental: tipo de documento, datos del encabezado,
-- tipo de fragmento y versión de procesamiento.
-- Ejecutar una vez, después de 005. Se puede volver a ejecutar.
--
-- documents
--   norma           'ISO 9001:2015' = norma; null = documento interno.
--   codigo, titulo_doc, revision, fecha_revision, emision,
--   realizado, aprobado: datos del encabezado del procedimiento
--   (por ejemplo PRO-02, Liderazgo, Rev. 07, 12/11/2020).
-- chunks.tipo       'contenido' | 'tabla' | 'historial'.
--                   El historial de cambios es un antecedente, no una
--                   instrucción vigente.
-- pipeline_version  Versión del lector con que se procesó un archivo de
--                   Drive. Si el lector mejora, sync_drive.py vuelve a
--                   procesar el archivo aunque no haya cambiado.

begin;

-- ---------------------------------------------------------------
-- 1) Columnas nuevas
-- ---------------------------------------------------------------

alter table public.documents add column if not exists codigo text;
alter table public.documents add column if not exists titulo_doc text;
alter table public.documents add column if not exists revision text;
alter table public.documents add column if not exists fecha_revision text;
alter table public.documents add column if not exists emision text;
alter table public.documents add column if not exists realizado text;
alter table public.documents add column if not exists aprobado text;

alter table public.chunks
  add column if not exists tipo text not null default 'contenido';

alter table public.drive_sync_state
  add column if not exists pipeline_version integer;

alter table public.drive_staged_documents
  add column if not exists pipeline_version integer not null default 0;
alter table public.drive_staged_documents
  add column if not exists doc_meta jsonb not null default '{}'::jsonb;

alter table public.drive_staged_chunks
  add column if not exists tipo text not null default 'contenido';

-- ---------------------------------------------------------------
-- 2) Preparación por lotes: ahora con versión, encabezado y tipo
-- ---------------------------------------------------------------

drop function if exists public.stage_drive_chunks(text, text, text, integer, jsonb);

create or replace function public.stage_drive_chunks(
  p_folder_id text,
  p_file_id text,
  p_md5 text,
  p_pipeline_version integer,
  p_doc_meta jsonb,
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
  v_version integer;
  v_count integer;
begin
  if nullif(btrim(p_folder_id), '') is null
     or nullif(btrim(p_file_id), '') is null
     or nullif(btrim(p_md5), '') is null then
    raise exception 'Faltan carpeta, archivo o huella.';
  end if;

  if p_pipeline_version is null or p_pipeline_version < 1 then
    raise exception 'Versión de procesamiento inválida.';
  end if;

  if p_total is null or p_total < 1 then
    raise exception 'Cantidad total de fragmentos inválida.';
  end if;

  if jsonb_typeof(p_doc_meta) is distinct from 'object' then
    raise exception 'Los datos del documento deben ser un objeto.';
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
       or coalesce(batch.item ->> 'tipo', 'contenido')
          not in ('contenido', 'tabla', 'historial')
  ) then
    raise exception 'Hay fragmentos sin índice válido, sin texto, sin embedding o con tipo desconocido.';
  end if;

  -- Solo se conserva la preparación de la versión actual del archivo.
  delete from public.drive_staged_documents
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 <> p_md5;

  select chunk_total, pipeline_version into v_total, v_version
  from public.drive_staged_documents
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 = p_md5
  for update;

  -- Otra fragmentación u otra versión del lector: se empieza de nuevo.
  if found and (v_total <> p_total or v_version <> p_pipeline_version) then
    delete from public.drive_staged_documents
    where folder_id = p_folder_id
      and file_id = p_file_id
      and content_md5 = p_md5;
  end if;

  insert into public.drive_staged_documents (
    folder_id, file_id, content_md5, chunk_total, pipeline_version, doc_meta
  )
  values (p_folder_id, p_file_id, p_md5, p_total, p_pipeline_version, p_doc_meta)
  on conflict (folder_id, file_id, content_md5) do update
    set doc_meta = excluded.doc_meta;

  insert into public.drive_staged_chunks (
    folder_id, file_id, content_md5, chunk_index,
    clausula, titulo, pagina, content, embedding, tipo
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
    (batch.item ->> 'embedding')::vector(768),
    coalesce(batch.item ->> 'tipo', 'contenido')
  from jsonb_array_elements(p_chunks) as batch(item)
  on conflict (folder_id, file_id, content_md5, chunk_index) do update
    set clausula = excluded.clausula,
        titulo = excluded.titulo,
        pagina = excluded.pagina,
        content = excluded.content,
        embedding = excluded.embedding,
        tipo = excluded.tipo;

  select count(*) into v_count
  from public.drive_staged_chunks
  where folder_id = p_folder_id
    and file_id = p_file_id
    and content_md5 = p_md5;

  return v_count;
end;
$$;

revoke all on function public.stage_drive_chunks(text, text, text, integer, jsonb, integer, jsonb)
from public, anon, authenticated;
grant execute on function public.stage_drive_chunks(text, text, text, integer, jsonb, integer, jsonb)
to service_role;

-- ---------------------------------------------------------------
-- 3) Confirmación de la carpeta
-- ---------------------------------------------------------------
-- p_apply: [{id, name, md5, modifiedTime, version, norma, pipeline}].
-- Si la huella y la versión del lector no cambiaron, se reutiliza el
-- contenido; si no, se toma de la preparación de esa huella y versión.

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
  v_pipeline integer;
  v_total integer;
  v_meta jsonb;
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
       or nullif(v_file ->> 'modifiedTime', '') is null
       or jsonb_typeof(v_file -> 'pipeline') is distinct from 'number' then
      raise exception 'Metadatos incompletos en un archivo a aplicar.';
    end if;
    v_pipeline := (v_file ->> 'pipeline')::integer;

    select * into v_state
    from public.drive_sync_state
    where folder_id = p_folder_id
      and file_id = v_file ->> 'id'
    for update;
    v_has_state := found;

    v_source := 'drive:' || p_folder_id || ':' || (v_file ->> 'id');

    if v_has_state then
      -- Conserva el ID del documento ya vinculado.
      v_doc_id := v_state.document_id;
      update public.documents
      set source = v_source,
          title = v_file ->> 'name',
          norma = nullif(btrim(v_file ->> 'norma'), ''),
          active = true
      where id = v_doc_id;
    else
      insert into public.documents (source, title, norma, active)
      values (v_source, v_file ->> 'name',
              nullif(btrim(v_file ->> 'norma'), ''), true)
      on conflict (source) do update
        set title = excluded.title,
            norma = excluded.norma,
            active = true
      returning id into v_doc_id;
    end if;

    if v_has_state
       and v_state.content_md5 = v_file ->> 'md5'
       and v_state.pipeline_version = v_pipeline
       and exists (select 1 from public.chunks where document_id = v_doc_id) then
      -- Mismo contenido y mismo lector: solo cambian metadatos o actividad.
      null;
    else
      select chunk_total, doc_meta into v_total, v_meta
      from public.drive_staged_documents
      where folder_id = p_folder_id
        and file_id = v_file ->> 'id'
        and content_md5 = v_file ->> 'md5'
        and pipeline_version = v_pipeline;

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

      update public.documents
      set codigo = v_meta ->> 'codigo',
          titulo_doc = v_meta ->> 'titulo',
          revision = v_meta ->> 'revision',
          fecha_revision = v_meta ->> 'fecha_revision',
          emision = v_meta ->> 'emision',
          realizado = v_meta ->> 'realizado',
          aprobado = v_meta ->> 'aprobado'
      where id = v_doc_id;

      delete from public.chunks where document_id = v_doc_id;

      insert into public.chunks (
        document_id, chunk_index, clausula, titulo, pagina, content,
        embedding, tipo
      )
      select v_doc_id, staged.chunk_index, staged.clausula, staged.titulo,
             staged.pagina, staged.content, staged.embedding, staged.tipo
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
      document_id, content_md5, pipeline_version, synced_at
    )
    values (
      p_folder_id, v_file ->> 'id', v_file ->> 'name', v_file ->> 'modifiedTime',
      v_file ->> 'version', v_doc_id, v_file ->> 'md5', v_pipeline, now()
    )
    on conflict (folder_id, file_id) do update
      set file_name = excluded.file_name,
          modified_time = excluded.modified_time,
          drive_version = excluded.drive_version,
          document_id = excluded.document_id,
          content_md5 = excluded.content_md5,
          pipeline_version = excluded.pipeline_version,
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
-- 4) Carga local: encabezado y tipo de fragmento
-- ---------------------------------------------------------------

drop function if exists public.replace_document(text, text, text, jsonb);

create or replace function public.replace_document(
  p_source text,
  p_title text,
  p_norma text,
  p_doc_meta jsonb,
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

  if jsonb_typeof(p_doc_meta) is distinct from 'object' then
    raise exception 'Los datos del documento deben ser un objeto.';
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
       or coalesce(item->>'tipo', 'contenido')
          not in ('contenido', 'tabla', 'historial')
  ) then
    raise exception 'Hay fragmentos sin texto, sin embedding o con tipo desconocido.';
  end if;

  insert into public.documents (
    source, title, norma, active, codigo, titulo_doc, revision,
    fecha_revision, emision, realizado, aprobado
  )
  values (
    p_source, p_title, p_norma, true,
    p_doc_meta ->> 'codigo', p_doc_meta ->> 'titulo', p_doc_meta ->> 'revision',
    p_doc_meta ->> 'fecha_revision', p_doc_meta ->> 'emision',
    p_doc_meta ->> 'realizado', p_doc_meta ->> 'aprobado'
  )
  on conflict (source) do update
    set title = excluded.title,
        norma = excluded.norma,
        active = true,
        codigo = excluded.codigo,
        titulo_doc = excluded.titulo_doc,
        revision = excluded.revision,
        fecha_revision = excluded.fecha_revision,
        emision = excluded.emision,
        realizado = excluded.realizado,
        aprobado = excluded.aprobado
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
    embedding,
    tipo
  )
  select
    v_document_id,
    (items.position - 1)::integer,
    items.item->>'clausula',
    items.item->>'titulo',
    (items.item->>'pagina')::integer,
    items.item->>'content',
    (items.item->>'embedding')::vector(768),
    coalesce(items.item->>'tipo', 'contenido')
  from jsonb_array_elements(p_chunks)
       with ordinality as items(item, position);

  return v_document_id;
end;
$$;

revoke all on function public.replace_document(text, text, text, jsonb, jsonb)
from public, anon, authenticated;
grant execute on function public.replace_document(text, text, text, jsonb, jsonb)
to service_role;

-- ---------------------------------------------------------------
-- 5) Búsqueda: devuelve tipo de documento, encabezado y tipo de fragmento
-- ---------------------------------------------------------------
-- Cambiar las columnas devueltas exige borrar y volver a crear la función.

drop function if exists public.hybrid_search(text, vector, integer, integer);

create function public.hybrid_search(
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
  score double precision,
  norma text,
  codigo text,
  titulo_doc text,
  revision text,
  fecha_revision text,
  tipo text
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
         f.score::double precision,
         d.norma,
         d.codigo,
         d.titulo_doc,
         d.revision,
         d.fecha_revision,
         c.tipo
  from fused f
  join public.chunks c on c.id = f.id
  join public.documents d on d.id = c.document_id
  where d.active
  order by f.score desc
  limit match_count;
$$;

revoke all on function public.hybrid_search(text, vector, integer, integer)
from public, anon, authenticated;
grant execute on function public.hybrid_search(text, vector, integer, integer)
to service_role;

notify pgrst, 'reload schema';

commit;
