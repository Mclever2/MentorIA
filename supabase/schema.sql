-- ══════════════════════════════════════════════════════════════════════════
-- MentorIA — Esquema de Supabase (historial de asesorías por usuario)
-- Ejecutar en: Supabase Dashboard → SQL Editor → New query → Run
-- ══════════════════════════════════════════════════════════════════════════

-- ── Conversaciones (asesorías) ──────────────────────────────────────────────
create table if not exists public.conversaciones (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  titulo      text not null default 'Nueva asesoría',
  creada_en   timestamptz not null default now()
);

-- ── Mensajes del chat ───────────────────────────────────────────────────────
-- metadata guarda la estructura del documento (tarjetas) y el doc_id del backend
create table if not exists public.mensajes (
  id               uuid primary key default gen_random_uuid(),
  conversacion_id  uuid not null references public.conversaciones (id) on delete cascade,
  rol              text not null check (rol in ('user', 'assistant')),
  contenido        text not null default '',
  tipo             text not null default 'texto',
  metadata         jsonb not null default '{}'::jsonb,
  creado_en        timestamptz not null default now()
);

create index if not exists mensajes_conversacion_idx
  on public.mensajes (conversacion_id, creado_en);

-- ── Row Level Security: cada usuario solo ve lo suyo ────────────────────────
alter table public.conversaciones enable row level security;
alter table public.mensajes enable row level security;

create policy "conversaciones propias - select"
  on public.conversaciones for select
  using (auth.uid() = user_id);

create policy "conversaciones propias - insert"
  on public.conversaciones for insert
  with check (auth.uid() = user_id);

create policy "conversaciones propias - update"
  on public.conversaciones for update
  using (auth.uid() = user_id);

create policy "conversaciones propias - delete"
  on public.conversaciones for delete
  using (auth.uid() = user_id);

create policy "mensajes de mis conversaciones - select"
  on public.mensajes for select
  using (
    exists (
      select 1 from public.conversaciones c
      where c.id = conversacion_id and c.user_id = auth.uid()
    )
  );

create policy "mensajes de mis conversaciones - insert"
  on public.mensajes for insert
  with check (
    exists (
      select 1 from public.conversaciones c
      where c.id = conversacion_id and c.user_id = auth.uid()
    )
  );

create policy "mensajes de mis conversaciones - delete"
  on public.mensajes for delete
  using (
    exists (
      select 1 from public.conversaciones c
      where c.id = conversacion_id and c.user_id = auth.uid()
    )
  );
