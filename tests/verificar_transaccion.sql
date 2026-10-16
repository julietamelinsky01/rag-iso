-- Prueba de las funciones de 005_sync_integrada.sql y 006_estructura_documental.sql.
-- Ejecutar DESPUÉS de las dos migraciones, en Supabase > SQL Editor.
-- No deja datos: todo termina con ROLLBACK.
-- Resultado esperado: un aviso que empieza con "OK:".

begin;

do $$
declare
  v_folder text := '__prueba_' || gen_random_uuid()::text;
  v_vec jsonb;
  v_meta jsonb;
  v_doc bigint;
  v_doc_local bigint;
  v_gen bigint;
  v_result jsonb;
  v_failed boolean;
begin
  select jsonb_agg(case when n = 1 then 1 else 0 end order by n)
  into v_vec
  from generate_series(1, 768) as n;

  -- 1) Preparación en dos lotes y confirmación de un archivo nuevo.
  perform public.stage_drive_chunks(v_folder, 'a', 'md5-a', 2,
    '{"codigo": "PRO-02", "revision": "07", "titulo": "Liderazgo"}'::jsonb, 2,
    jsonb_build_array(jsonb_build_object(
      'chunk_index', 0, 'content', 'Texto original uno', 'embedding', v_vec)));
  perform public.stage_drive_chunks(v_folder, 'a', 'md5-a', 2,
    '{"codigo": "PRO-02", "revision": "07", "titulo": "Liderazgo"}'::jsonb, 2,
    jsonb_build_array(jsonb_build_object(
      'chunk_index', 1, 'content', 'Texto original dos', 'embedding', v_vec,
      'clausula', '3.3', 'pagina', 3, 'tipo', 'historial')));

  v_meta := jsonb_build_object('id', 'a', 'name', 'Original.pdf',
    'md5', 'md5-a', 'modifiedTime', 't1', 'version', '1',
    'norma', 'ISO 9001:2015', 'pipeline', 2);
  v_result := public.reconcile_drive_folder(
    v_folder, 0, '["a"]'::jsonb, jsonb_build_array(v_meta));

  select document_id into v_doc
  from public.drive_sync_state where folder_id = v_folder and file_id = 'a';

  if (select count(*) from public.chunks where document_id = v_doc) <> 2 then
    raise exception 'Falló la carga desde la preparación';
  end if;
  if exists (select 1 from public.drive_staged_documents where folder_id = v_folder) then
    raise exception 'La preparación no se limpió';
  end if;
  if (select norma from public.documents where id = v_doc) is distinct from 'ISO 9001:2015' then
    raise exception 'No se guardó la norma';
  end if;
  if not exists (select 1 from public.documents
                 where id = v_doc and codigo = 'PRO-02' and revision = '07'
                   and titulo_doc = 'Liderazgo') then
    raise exception 'No se guardaron los datos del encabezado';
  end if;
  if (select tipo from public.chunks where document_id = v_doc and chunk_index = 1)
     is distinct from 'historial' then
    raise exception 'No se guardó el tipo de fragmento';
  end if;

  -- 2) Renombrado con el mismo contenido: sin preparación nueva.
  -- También deja de ser norma (norma nula = documento interno).
  v_meta := v_meta || '{"name": "Renombrado.pdf", "modifiedTime": "t2", "version": "2", "norma": null}';
  perform public.reconcile_drive_folder(
    v_folder, 1, '["a"]'::jsonb, jsonb_build_array(v_meta));
  if not exists (select 1 from public.documents
                 where id = v_doc and title = 'Renombrado.pdf' and active
                   and norma is null) then
    raise exception 'Falló el renombrado o el cambio de tipo';
  end if;

  -- 3) Un archivo nuevo que falló: figura presente, no se aplica,
  --    y no afecta al resto.
  perform public.reconcile_drive_folder(
    v_folder, 2, '["a", "b"]'::jsonb, jsonb_build_array(v_meta));
  if exists (select 1 from public.drive_sync_state
             where folder_id = v_folder and file_id = 'b') then
    raise exception 'Se registró un archivo que no se aplicó';
  end if;

  -- 4) Contenido nuevo sin preparación completa: debe rechazarse.
  perform public.stage_drive_chunks(v_folder, 'b', 'md5-b', 2, '{}'::jsonb, 3,
    jsonb_build_array(jsonb_build_object(
      'chunk_index', 0, 'content', 'Parcial', 'embedding', v_vec)));
  v_failed := false;
  begin
    perform public.reconcile_drive_folder(v_folder, 3, '["a", "b"]'::jsonb,
      jsonb_build_array(v_meta, jsonb_build_object('id', 'b', 'name', 'B.pdf',
        'md5', 'md5-b', 'modifiedTime', 't1', 'version', '1', 'pipeline', 2)));
  exception when raise_exception then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Se aceptó una preparación incompleta';
  end if;

  -- 5) Retiro y reaparición con el mismo ID.
  perform public.reconcile_drive_folder(v_folder, 3, '[]'::jsonb, '[]'::jsonb);
  if (select active from public.documents where id = v_doc) then
    raise exception 'Falló la desactivación';
  end if;
  if exists (select 1 from public.drive_staged_documents where folder_id = v_folder) then
    raise exception 'Quedó preparación de un archivo retirado';
  end if;

  perform public.reconcile_drive_folder(
    v_folder, 4, '["a"]'::jsonb, jsonb_build_array(v_meta));
  if not (select active from public.documents where id = v_doc) then
    raise exception 'Falló la reactivación';
  end if;

  -- 6) Un vector inválido en la preparación falla sin dejar nada.
  v_failed := false;
  begin
    perform public.stage_drive_chunks(v_folder, 'a', 'md5-c', 2, '{}'::jsonb, 1,
      jsonb_build_array(jsonb_build_object(
        'chunk_index', 0, 'content', 'Nuevo', 'embedding', '[1, 2, 3]'::jsonb)));
  exception when data_exception then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Se aceptó un vector inválido';
  end if;
  if not exists (select 1 from public.chunks
                 where document_id = v_doc and content = 'Texto original uno') then
    raise exception 'Se perdió el contenido vigente';
  end if;

  -- 7) Otra versión del lector con la misma huella exige preparar de nuevo.
  v_failed := false;
  begin
    perform public.reconcile_drive_folder(v_folder, 5, '["a"]'::jsonb,
      jsonb_build_array(v_meta || '{"pipeline": 3}'));
  exception when raise_exception then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Se aceptó un cambio de lector sin reprocesar';
  end if;

  -- 8) Una ejecución basada en un estado viejo se rechaza.
  v_failed := false;
  begin
    perform public.reconcile_drive_folder(v_folder, 0, '[]'::jsonb, '[]'::jsonb);
  exception when raise_exception then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Se aceptó una ejecución obsoleta';
  end if;

  select generation into v_gen
  from public.drive_sync_control where folder_id = v_folder;
  if v_gen <> 5 then
    raise exception 'Generación inesperada: %', v_gen;
  end if;

  -- 9) Carga local con encabezado y tipo de fragmento.
  v_doc_local := public.replace_document(v_folder || '-local.docx', 'Local', null,
    '{"codigo": "PRO-09", "revision": "01"}'::jsonb,
    jsonb_build_array(jsonb_build_object('content', 'Tabla local', 'embedding', v_vec,
      'tipo', 'tabla')));
  if not exists (select 1 from public.documents d join public.chunks c on c.document_id = d.id
                 where d.id = v_doc_local and d.codigo = 'PRO-09' and d.active
                   and c.tipo = 'tabla') then
    raise exception 'Falló la carga local con encabezado';
  end if;

  -- 10) La búsqueda devuelve el nombre legible y excluye inactivos.
  if not exists (
    select 1 from public.hybrid_search('Texto original', v_vec::text::vector, 50)
    where document_id = v_doc and source = 'Renombrado.pdf' and norma is null
      and codigo = 'PRO-02'
  ) then
    raise exception 'La búsqueda no devolvió el documento activo';
  end if;

  update public.documents set active = false where id = v_doc;
  if exists (
    select 1 from public.hybrid_search('Texto original', v_vec::text::vector, 50)
    where document_id = v_doc
  ) then
    raise exception 'La búsqueda devolvió un documento inactivo';
  end if;

  raise notice 'OK: preparación por lotes, encabezado, tipo, versión del lector, carga local, norma, renombrado, aislamiento de fallos, '
               'retiro, reaparición, rollback, conflicto y búsqueda';
end $$;

rollback;
