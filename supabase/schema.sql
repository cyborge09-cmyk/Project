-- Chess Board Project Management Tool -- database schema
-- Apply with: supabase db push, or paste into the Supabase SQL editor.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- enums ----
do $$ begin
  create type project_status as enum ('planning', 'active', 'blocked', 'completed', 'on_hold');
exception when duplicate_object then null; end $$;

do $$ begin
  create type chess_piece as enum ('king', 'queen', 'rook', 'bishop', 'knight', 'pawn');
exception when duplicate_object then null; end $$;

-- ------------------------------------------------------------- profiles ----
create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null,
  full_name   text,
  avatar_url  text,
  department  text,
  job_title   text,
  skills      text[] not null default '{}',
  theme       text not null default 'light' check (theme in ('light', 'dark')),
  created_at  timestamptz not null default now()
);

-- Keep public.profiles in sync with auth.users.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1))
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- --------------------------------------------------------------- boards ----
create table if not exists public.boards (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  description text,
  rows        int  not null default 8 check (rows between 2 and 16),
  cols        int  not null default 8 check (cols between 2 and 16),
  owner_id    uuid not null references public.profiles (id) on delete cascade,
  archived    boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.board_members (
  board_id  uuid not null references public.boards (id) on delete cascade,
  user_id   uuid not null references public.profiles (id) on delete cascade,
  role      text not null default 'member' check (role in ('owner', 'admin', 'member', 'viewer')),
  added_at  timestamptz not null default now(),
  primary key (board_id, user_id)
);

-- ------------------------------------------------------------- projects ----
create table if not exists public.projects (
  id          uuid primary key default gen_random_uuid(),
  board_id    uuid not null references public.boards (id) on delete cascade,
  name        text not null,
  description text,
  status      project_status not null default 'planning',
  progress    int not null default 0 check (progress between 0 and 100),
  start_date  date,
  deadline    date,
  pos_x       int not null check (pos_x >= 0),
  pos_y       int not null check (pos_y >= 0),
  tags        text[] not null default '{}',
  blockers    text[] not null default '{}',
  velocity    numeric,
  cycle_time  numeric,
  created_by  uuid references public.profiles (id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (board_id, pos_x, pos_y)
);

create index if not exists projects_board_idx  on public.projects (board_id);
create index if not exists projects_status_idx on public.projects (board_id, status);

create table if not exists public.project_members (
  id               uuid primary key default gen_random_uuid(),
  project_id       uuid not null references public.projects (id) on delete cascade,
  user_id          uuid not null references public.profiles (id) on delete cascade,
  piece            chess_piece not null default 'pawn',
  hours_allocated  numeric not null default 0 check (hours_allocated >= 0),
  active           boolean not null default true,
  joined_at        timestamptz not null default now(),
  unique (project_id, user_id)
);

create index if not exists project_members_user_idx on public.project_members (user_id);

-- "Maximum 1 King and 1 Queen per project" (section 8.1 of the plan).
create unique index if not exists project_members_one_royal_idx
  on public.project_members (project_id, piece)
  where piece in ('king', 'queen');

create table if not exists public.project_dependencies (
  project_id     uuid not null references public.projects (id) on delete cascade,
  depends_on_id  uuid not null references public.projects (id) on delete cascade,
  primary key (project_id, depends_on_id),
  check (project_id <> depends_on_id)
);

create table if not exists public.comments (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects (id) on delete cascade,
  author_id   uuid not null references public.profiles (id) on delete cascade,
  body        text not null check (length(btrim(body)) > 0),
  created_at  timestamptz not null default now()
);

create index if not exists comments_project_idx on public.comments (project_id, created_at desc);

create table if not exists public.activity (
  id          uuid primary key default gen_random_uuid(),
  board_id    uuid not null references public.boards (id) on delete cascade,
  project_id  uuid references public.projects (id) on delete cascade,
  actor_id    uuid references public.profiles (id) on delete set null,
  action      text not null,
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists activity_board_idx on public.activity (board_id, created_at desc);

-- ------------------------------------------------------------- triggers ----
create or replace function public.touch_updated_at()
returns trigger language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists boards_touch on public.boards;
create trigger boards_touch before update on public.boards
  for each row execute function public.touch_updated_at();

drop trigger if exists projects_touch on public.projects;
create trigger projects_touch before update on public.projects
  for each row execute function public.touch_updated_at();

-- The board owner is always a member, so access checks have a single source.
create or replace function public.add_owner_as_member()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.board_members (board_id, user_id, role)
  values (new.id, new.owner_id, 'owner')
  on conflict (board_id, user_id) do update set role = 'owner';
  return new;
end;
$$;

drop trigger if exists boards_owner_member on public.boards;
create trigger boards_owner_member after insert on public.boards
  for each row execute function public.add_owner_as_member();

-- ---------------------------------------------------- access helper (RLS) --
-- SECURITY DEFINER so board_members policies do not recurse into themselves.
create or replace function public.can_access_board(b uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.board_members m
    where m.board_id = b and m.user_id = auth.uid()
  );
$$;

create or replace function public.can_edit_board(b uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.board_members m
    where m.board_id = b
      and m.user_id = auth.uid()
      and m.role in ('owner', 'admin', 'member')
  );
$$;

create or replace function public.can_access_project(p uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select public.can_access_board((select board_id from public.projects where id = p));
$$;

create or replace function public.can_edit_project(p uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select public.can_edit_board((select board_id from public.projects where id = p));
$$;

-- ------------------------------------------------------------------ RLS ----
alter table public.profiles             enable row level security;
alter table public.boards               enable row level security;
alter table public.board_members        enable row level security;
alter table public.projects             enable row level security;
alter table public.project_members      enable row level security;
alter table public.project_dependencies enable row level security;
alter table public.comments             enable row level security;
alter table public.activity             enable row level security;

drop policy if exists profiles_read   on public.profiles;
drop policy if exists profiles_update on public.profiles;
create policy profiles_read   on public.profiles for select using (auth.uid() is not null);
create policy profiles_update on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists boards_read   on public.boards;
drop policy if exists boards_insert on public.boards;
drop policy if exists boards_update on public.boards;
drop policy if exists boards_delete on public.boards;
create policy boards_read   on public.boards for select using (public.can_access_board(id));
create policy boards_insert on public.boards for insert with check (owner_id = auth.uid());
create policy boards_update on public.boards for update using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy boards_delete on public.boards for delete using (owner_id = auth.uid());

drop policy if exists board_members_read  on public.board_members;
drop policy if exists board_members_write on public.board_members;
create policy board_members_read  on public.board_members for select using (public.can_access_board(board_id));
create policy board_members_write on public.board_members for all
  using (exists (select 1 from public.boards b where b.id = board_id and b.owner_id = auth.uid()))
  with check (exists (select 1 from public.boards b where b.id = board_id and b.owner_id = auth.uid()));

drop policy if exists projects_read  on public.projects;
drop policy if exists projects_write on public.projects;
create policy projects_read  on public.projects for select using (public.can_access_board(board_id));
create policy projects_write on public.projects for all
  using (public.can_edit_board(board_id)) with check (public.can_edit_board(board_id));

drop policy if exists project_members_read  on public.project_members;
drop policy if exists project_members_write on public.project_members;
create policy project_members_read  on public.project_members for select using (public.can_access_project(project_id));
create policy project_members_write on public.project_members for all
  using (public.can_edit_project(project_id)) with check (public.can_edit_project(project_id));

drop policy if exists project_dependencies_read  on public.project_dependencies;
drop policy if exists project_dependencies_write on public.project_dependencies;
create policy project_dependencies_read  on public.project_dependencies for select using (public.can_access_project(project_id));
create policy project_dependencies_write on public.project_dependencies for all
  using (public.can_edit_project(project_id)) with check (public.can_edit_project(project_id));

drop policy if exists comments_read   on public.comments;
drop policy if exists comments_insert on public.comments;
drop policy if exists comments_delete on public.comments;
create policy comments_read   on public.comments for select using (public.can_access_project(project_id));
create policy comments_insert on public.comments for insert with check (author_id = auth.uid() and public.can_access_project(project_id));
create policy comments_delete on public.comments for delete using (author_id = auth.uid());

drop policy if exists activity_read   on public.activity;
drop policy if exists activity_insert on public.activity;
create policy activity_read   on public.activity for select using (public.can_access_board(board_id));
create policy activity_insert on public.activity for insert with check (public.can_access_board(board_id) and actor_id = auth.uid());

-- --------------------------------------------------------------- grants ----
-- Postgres grants EXECUTE on new functions to PUBLIC, which would expose every
-- one of these over /rest/v1/rpc. Revoking from anon/authenticated is not enough:
-- the PUBLIC grant is the one that has to go.
revoke execute on function public.handle_new_user()     from public, anon, authenticated;
revoke execute on function public.add_owner_as_member() from public, anon, authenticated;
revoke execute on function public.touch_updated_at()    from public, anon, authenticated;

revoke execute on function public.can_access_board(uuid)   from public, anon;
revoke execute on function public.can_edit_board(uuid)     from public, anon;
revoke execute on function public.can_access_project(uuid) from public, anon;
revoke execute on function public.can_edit_project(uuid)   from public, anon;

-- The policies above call these as the signed-in role, so it keeps EXECUTE.
-- They only ever report whether the *caller* may touch a board they already name.
grant execute on function public.can_access_board(uuid)   to authenticated;
grant execute on function public.can_edit_board(uuid)     to authenticated;
grant execute on function public.can_access_project(uuid) to authenticated;
grant execute on function public.can_edit_project(uuid)   to authenticated;
