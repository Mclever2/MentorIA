-- ══════════════════════════════════════════════════════════════════════════
-- MentorIA — Esquema v2 (persistencia de sesión por chat)
-- Ejecutar DESPUÉS de schema.sql, en: Supabase Dashboard → SQL Editor → Run
-- Idempotente: se puede correr varias veces sin error.
-- ══════════════════════════════════════════════════════════════════════════

-- ── 1. Metadata del proyecto indexado, atada a cada conversación ────────────
-- El vector store (Chroma) vive en memoria del backend y no es serializable;
-- aquí guardamos lo necesario para re-indexar el PDF al reabrir el chat:
--   doc_storage_path → ruta del PDF en el bucket 'tesis'
--   doc_toc / doc_stats → estructura ya detectada (para mostrarla sin re-procesar)
--   doc_memoria → secciones evaluadas + texto corregido incorporado (RAG)
alter table public.conversaciones add column if not exists doc_nombre        text;
alter table public.conversaciones add column if not exists doc_hash          text;
alter table public.conversaciones add column if not exists doc_storage_path  text;
alter table public.conversaciones add column if not exists doc_toc           jsonb;
alter table public.conversaciones add column if not exists doc_stats         jsonb;
alter table public.conversaciones add column if not exists doc_memoria       jsonb not null default '{}'::jsonb;

-- ── 2. Bucket de Storage para los PDFs de tesis (privado) ───────────────────
insert into storage.buckets (id, name, public)
values ('tesis', 'tesis', false)
on conflict (id) do nothing;

-- ── 3. RLS de Storage: cada usuario solo accede a su propia carpeta ─────────
-- Las rutas son '{user_id}/{conversation_id}.pdf', así que el primer segmento
-- de la ruta debe coincidir con el uid del usuario autenticado.
drop policy if exists "tesis: leer propios"    on storage.objects;
drop policy if exists "tesis: subir propios"   on storage.objects;
drop policy if exists "tesis: actualizar propios" on storage.objects;
drop policy if exists "tesis: borrar propios"  on storage.objects;

create policy "tesis: leer propios"
  on storage.objects for select
  using (bucket_id = 'tesis' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "tesis: subir propios"
  on storage.objects for insert
  with check (bucket_id = 'tesis' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "tesis: actualizar propios"
  on storage.objects for update
  using (bucket_id = 'tesis' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "tesis: borrar propios"
  on storage.objects for delete
  using (bucket_id = 'tesis' and (storage.foldername(name))[1] = auth.uid()::text);
