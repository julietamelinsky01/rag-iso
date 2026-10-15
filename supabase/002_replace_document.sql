-- Reemplazo atómico de documentos y fragmentos.
-- Si una parte falla, se conserva la versión anterior.

begin;

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

  -- Crea o actualiza el documento.
  -- Bloquea su fila para ordenar actualizaciones simultáneas.
  insert into public.documents (source, title, norma)
  values (p_source, p_title, p_norma)
  on conflict (source) do update
    set title = excluded.title,
        norma = excluded.norma
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

-- Solo el backend puede ejecutar esta función.
revoke all on function public.replace_document(text, text, text, jsonb)
from public, anon, authenticated;

grant execute on function public.replace_document(text, text, text, jsonb)
to service_role;

commit;