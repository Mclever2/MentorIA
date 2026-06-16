-- ══════════════════════════════════════════════════════════════════════════
-- MentorIA — Esquema v3 (rúbrica personalizada + perfil de universidad)
-- Ejecutar DESPUÉS de schema.sql y schema_v2.sql, en: Supabase → SQL Editor → Run
-- Idempotente: se puede correr varias veces sin error.
-- ══════════════════════════════════════════════════════════════════════════

-- ── 1. Snapshot por conversación ────────────────────────────────────────────
-- Cada chat congela qué rúbrica y qué perfil de universidad estaban activos
-- cuando se creó/usó. Así, si en otro chat se cambia la rúbrica o el reglamento,
-- este chat sigue usando el suyo (snapshot inmutable salvo edición explícita).
--   rubrica            → rúbrica parseada + mapa_secciones (o null = UPAO por defecto)
--   perfil_universidad → { universidad, programa, nivel, contexto_institucional,
--                          enfasis, fuente } (o null = sin reglamento adicional)
alter table public.conversaciones add column if not exists rubrica            jsonb;
alter table public.conversaciones add column if not exists perfil_universidad jsonb;

-- ── 2. Preferencias del usuario (default que heredan los chats nuevos) ───────
-- Singleton por usuario. El navbar guarda aquí la rúbrica / perfil "actual";
-- al crear un chat nuevo se copia este default a la fila de la conversación.
create table if not exists public.preferencias_usuario (
  user_id            uuid primary key references auth.users (id) on delete cascade,
  rubrica            jsonb,
  perfil_universidad jsonb,
  actualizado_en     timestamptz not null default now()
);

-- ── 3. Row Level Security: cada usuario solo ve/edita lo suyo ────────────────
alter table public.preferencias_usuario enable row level security;

drop policy if exists "preferencias propias - select" on public.preferencias_usuario;
drop policy if exists "preferencias propias - insert" on public.preferencias_usuario;
drop policy if exists "preferencias propias - update" on public.preferencias_usuario;
drop policy if exists "preferencias propias - delete" on public.preferencias_usuario;

create policy "preferencias propias - select"
  on public.preferencias_usuario for select
  using (auth.uid() = user_id);

create policy "preferencias propias - insert"
  on public.preferencias_usuario for insert
  with check (auth.uid() = user_id);

create policy "preferencias propias - update"
  on public.preferencias_usuario for update
  using (auth.uid() = user_id);

create policy "preferencias propias - delete"
  on public.preferencias_usuario for delete
  using (auth.uid() = user_id);
