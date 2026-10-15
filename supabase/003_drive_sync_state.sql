-- Registro de las versiones de Drive procesadas correctamente.

begin;

create table if not exists public.drive_sync_state (
  folder_id text not null,
  file_id text not null,
  file_name text not null,
  modified_time text not null,
  drive_version text,
  document_id bigint not null
    references public.documents(id) on delete cascade,
  synced_at timestamptz not null default now(),
  primary key (folder_id, file_id)
);

alter table public.drive_sync_state enable row level security;

revoke all on public.drive_sync_state from anon, authenticated;

grant select, insert, update, delete
  on public.drive_sync_state to service_role;

commit;