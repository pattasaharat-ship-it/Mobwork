-- โต๊ะงานสายเที่ยว: database setup for Supabase.
-- Run once: Supabase dashboard > SQL Editor > New query > paste this file > Run.
-- Safe to run again.

create extension if not exists pgcrypto;

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'ทีมของฉัน',
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists public.workspace_members (
  workspace_id uuid not null references public.workspaces on delete cascade,
  user_id uuid not null references auth.users on delete cascade,
  role text not null default 'editor' check (role in ('owner','editor')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

-- Every record in the app (clients, projects, events, invoices, ...) is one row.
-- col = which list it belongs to, data = the record itself.
create table if not exists public.app_docs (
  workspace_id uuid not null references public.workspaces on delete cascade,
  col text not null,
  id text not null check (length(id) between 1 and 80),
  data jsonb not null check (jsonb_typeof(data) = 'object' and pg_column_size(data) < 200000),
  updated_at timestamptz not null default now(),
  updated_by uuid default auth.uid(),
  primary key (workspace_id, col, id)
);
-- which list a row belongs to (clients, projects, content, ...); a pattern so new features need no migration
alter table public.app_docs drop constraint if exists app_docs_col_check;
alter table public.app_docs add constraint app_docs_col_check check (col ~ '^[a-z_]{1,40}$');
create index if not exists app_docs_activity on public.app_docs (workspace_id, updated_at desc) where col = 'activity';

create or replace function public.is_member(ws uuid) returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from workspace_members where workspace_id = ws and user_id = auth.uid());
$$;
create or replace function public.is_owner(ws uuid) returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from workspace_members where workspace_id = ws and user_id = auth.uid() and role = 'owner');
$$;

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.app_docs enable row level security;

drop policy if exists ws_read on public.workspaces;
create policy ws_read on public.workspaces for select using (public.is_member(id));
drop policy if exists ws_rename on public.workspaces;
create policy ws_rename on public.workspaces for update using (public.is_owner(id)) with check (public.is_owner(id));
drop policy if exists wm_read on public.workspace_members;
create policy wm_read on public.workspace_members for select using (public.is_member(workspace_id));
drop policy if exists docs_all on public.app_docs;
create policy docs_all on public.app_docs for all
  using (public.is_member(workspace_id)) with check (public.is_member(workspace_id));

-- First sign-in: return the user's workspace, creating one if needed.
create or replace function public.my_workspace() returns uuid
language plpgsql security definer set search_path = public as $$
declare ws uuid;
begin
  if auth.uid() is null then raise exception 'not signed in'; end if;
  select workspace_id into ws from workspace_members where user_id = auth.uid() order by created_at limit 1;
  if ws is null then
    insert into workspaces (created_by) values (auth.uid()) returning id into ws;
    insert into workspace_members (workspace_id, user_id, role) values (ws, auth.uid(), 'owner');
  end if;
  return ws;
end $$;

-- Team: the owner adds someone who has already signed up, by email.
create or replace function public.add_member(ws uuid, member_email text) returns text
language plpgsql security definer set search_path = public as $$
declare uid uuid;
begin
  if not public.is_owner(ws) then raise exception 'only the owner can add members'; end if;
  select id into uid from auth.users where lower(email) = lower(trim(member_email));
  if uid is null then return 'not_found'; end if;
  if exists (select 1 from workspace_members where user_id = uid and workspace_id <> ws) then
    -- move them out of their own empty workspace into this team
    delete from workspaces w where w.created_by = uid and w.id <> ws
      and not exists (select 1 from app_docs d where d.workspace_id = w.id and d.col <> 'activity');
  end if;
  insert into workspace_members (workspace_id, user_id, role) values (ws, uid, 'editor') on conflict do nothing;
  return 'ok';
end $$;

create or replace function public.remove_member(ws uuid, member uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_owner(ws) then raise exception 'only the owner can remove members'; end if;
  if member = auth.uid() then raise exception 'owner cannot remove themselves'; end if;
  delete from workspace_members where workspace_id = ws and user_id = member;
end $$;

create or replace function public.list_members(ws uuid) returns table (user_id uuid, email text, role text)
language sql security definer stable set search_path = public as $$
  select m.user_id, u.email::text, m.role from workspace_members m join auth.users u on u.id = m.user_id
  where m.workspace_id = ws and public.is_member(ws) order by m.created_at;
$$;

revoke execute on function public.my_workspace(), public.add_member(uuid,text), public.remove_member(uuid,uuid), public.list_members(uuid) from public, anon;
grant execute on function public.my_workspace(), public.add_member(uuid,text), public.remove_member(uuid,uuid), public.list_members(uuid) to authenticated;

-- Live sync between phone and computer
do $$ begin
  alter publication supabase_realtime add table public.app_docs;
exception when duplicate_object then null; when undefined_object then null; end $$;
