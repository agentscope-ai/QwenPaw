-- QwenPaw blog views + likes
-- Run once in Supabase Dashboard → SQL Editor → New query → Run

create table if not exists public.blog_stats (
  slug text primary key,
  views bigint not null default 0 check (views >= 0),
  likes bigint not null default 0 check (likes >= 0),
  updated_at timestamptz not null default now()
);

create index if not exists blog_stats_views_idx on public.blog_stats (views desc);

alter table public.blog_stats enable row level security;

-- Public read for list + article pages
drop policy if exists "blog_stats_select_public" on public.blog_stats;
create policy "blog_stats_select_public"
  on public.blog_stats
  for select
  to anon, authenticated
  using (true);

-- No direct insert/update/delete for anon — writes go through RPCs below

create or replace function public.increment_blog_view(p_slug text)
returns public.blog_stats
language plpgsql
security definer
set search_path = public
as $$
declare
  result public.blog_stats;
begin
  if p_slug is null or length(trim(p_slug)) = 0 then
    raise exception 'slug required';
  end if;

  insert into public.blog_stats (slug, views, likes)
  values (p_slug, 1, 0)
  on conflict (slug) do update
    set views = public.blog_stats.views + 1,
        updated_at = now()
  returning * into result;

  return result;
end;
$$;

create or replace function public.increment_blog_like(p_slug text)
returns public.blog_stats
language plpgsql
security definer
set search_path = public
as $$
declare
  result public.blog_stats;
begin
  if p_slug is null or length(trim(p_slug)) = 0 then
    raise exception 'slug required';
  end if;

  insert into public.blog_stats (slug, views, likes)
  values (p_slug, 0, 1)
  on conflict (slug) do update
    set likes = public.blog_stats.likes + 1,
        updated_at = now()
  returning * into result;

  return result;
end;
$$;

create or replace function public.decrement_blog_like(p_slug text)
returns public.blog_stats
language plpgsql
security definer
set search_path = public
as $$
declare
  result public.blog_stats;
begin
  if p_slug is null or length(trim(p_slug)) = 0 then
    raise exception 'slug required';
  end if;

  insert into public.blog_stats (slug, views, likes)
  values (p_slug, 0, 0)
  on conflict (slug) do update
    set likes = greatest(public.blog_stats.likes - 1, 0),
        updated_at = now()
  returning * into result;

  return result;
end;
$$;

revoke all on function public.increment_blog_view(text) from public;
revoke all on function public.increment_blog_like(text) from public;
revoke all on function public.decrement_blog_like(text) from public;

grant execute on function public.increment_blog_view(text) to anon, authenticated;
grant execute on function public.increment_blog_like(text) to anon, authenticated;
grant execute on function public.decrement_blog_like(text) to anon, authenticated;

grant select on table public.blog_stats to anon, authenticated;
