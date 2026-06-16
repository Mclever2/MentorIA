// Persistencia de la rúbrica y el perfil de universidad:
//   - preferencias_usuario  → default del usuario (lo heredan los chats nuevos)
//   - conversaciones        → snapshot por chat (lo que ESE chat usó)
// Sin rúbrica → UPAO por defecto; sin perfil → el que el agente ya tenga.
import { supabase } from "@/lib/supabase";
import type { PerfilUniversidad, RubricaPersist } from "@/types";

export interface Recursos {
  rubrica: RubricaPersist | null;
  perfil: PerfilUniversidad | null;
}

export const recursosVacios = (): Recursos => ({ rubrica: null, perfil: null });

/** Default del usuario (heredado por chats nuevos). */
export async function leerPreferencias(): Promise<Recursos> {
  if (!supabase) return recursosVacios();
  const { data } = await supabase
    .from("preferencias_usuario")
    .select("rubrica, perfil_universidad")
    .maybeSingle();
  return {
    rubrica: (data?.rubrica as RubricaPersist) ?? null,
    perfil: (data?.perfil_universidad as PerfilUniversidad) ?? null,
  };
}

export async function guardarPreferencias(userId: string, r: Recursos): Promise<void> {
  if (!supabase) return;
  await supabase.from("preferencias_usuario").upsert({
    user_id: userId,
    rubrica: r.rubrica,
    perfil_universidad: r.perfil,
    actualizado_en: new Date().toISOString(),
  });
}

/** Snapshot del chat. */
export async function leerRecursosConversacion(convId: string): Promise<Recursos> {
  if (!supabase) return recursosVacios();
  const { data } = await supabase
    .from("conversaciones")
    .select("rubrica, perfil_universidad")
    .eq("id", convId)
    .single();
  return {
    rubrica: (data?.rubrica as RubricaPersist) ?? null,
    perfil: (data?.perfil_universidad as PerfilUniversidad) ?? null,
  };
}

export async function guardarRecursosConversacion(convId: string, r: Recursos): Promise<void> {
  if (!supabase) return;
  await supabase
    .from("conversaciones")
    .update({ rubrica: r.rubrica, perfil_universidad: r.perfil })
    .eq("id", convId);
}
