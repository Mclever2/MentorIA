// Persistencia de la sesión por chat: PDF en Supabase Storage + metadata del
// documento en la fila de la conversación. Permite reabrir un chat del historial
// y re-indexar el proyecto para seguir el hilo exactamente donde quedó.
import { subirDocumento, type DocMemoria, type DocumentoInfo } from "@/lib/api";
import { supabase } from "@/lib/supabase";

const BUCKET = "tesis";

export interface DocPersistido {
  nombre: string;
  hash: string;
  storagePath: string;
  toc: Record<string, number>;
  stats: DocumentoInfo["stats"];
  memoria: DocMemoria;
}

export const memoriaVacia = (): DocMemoria => ({
  evaluadas: [],
  aplicadas: {},
  pendientes: {},
});

/** Sube el PDF al bucket privado del usuario (1 PDF por conversación, sobrescribe). */
export async function guardarPdfEnStorage(
  userId: string,
  convId: string,
  archivo: File,
): Promise<string | null> {
  if (!supabase) return null;
  const path = `${userId}/${convId}.pdf`;
  const { error } = await supabase.storage
    .from(BUCKET)
    .upload(path, archivo, { upsert: true, contentType: "application/pdf" });
  if (error) {
    console.warn("[sesion] No se pudo guardar el PDF en Storage:", error.message);
    return null;
  }
  return path;
}

/** Guarda/actualiza la metadata del documento en la fila de la conversación. */
export async function guardarDocEnConversacion(
  convId: string,
  info: DocumentoInfo,
  storagePath: string | null,
  memoria: DocMemoria,
): Promise<void> {
  if (!supabase) return;
  await supabase
    .from("conversaciones")
    .update({
      doc_nombre: info.nombre,
      doc_hash: info.hash,
      doc_storage_path: storagePath,
      doc_toc: info.estructura_toc,
      doc_stats: info.stats,
      doc_memoria: memoria,
    })
    .eq("id", convId);
}

/** Actualiza solo la memoria (evaluadas / texto corregido) tras una revisión. */
export async function guardarMemoria(convId: string, memoria: DocMemoria): Promise<void> {
  if (!supabase) return;
  await supabase.from("conversaciones").update({ doc_memoria: memoria }).eq("id", convId);
}

/** Borra el PDF de Storage (al subir una versión nueva o eliminar el chat). */
export async function borrarPdfDeStorage(storagePath: string | null): Promise<void> {
  if (!supabase || !storagePath) return;
  await supabase.storage.from(BUCKET).remove([storagePath]);
}

/** Lee la metadata del documento persistida en una conversación. */
export async function leerDocPersistido(convId: string): Promise<DocPersistido | null> {
  if (!supabase) return null;
  const { data } = await supabase
    .from("conversaciones")
    .select("doc_nombre, doc_hash, doc_storage_path, doc_toc, doc_stats, doc_memoria")
    .eq("id", convId)
    .single();
  if (!data || !data.doc_storage_path) return null;
  return {
    nombre: data.doc_nombre ?? "tesis.pdf",
    hash: data.doc_hash ?? "",
    storagePath: data.doc_storage_path,
    toc: data.doc_toc ?? {},
    stats: data.doc_stats ?? [],
    memoria: (data.doc_memoria as DocMemoria) ?? memoriaVacia(),
  };
}

/** Re-indexa el PDF desde Storage y reaplica la memoria → DocumentoInfo vivo. */
export async function rehidratar(persistido: DocPersistido): Promise<DocumentoInfo | null> {
  if (!supabase) return null;
  const { data, error } = await supabase.storage.from(BUCKET).download(persistido.storagePath);
  if (error || !data) {
    console.warn("[sesion] No se pudo descargar el PDF para rehidratar:", error?.message);
    return null;
  }
  const archivo = new File([data], persistido.nombre, { type: "application/pdf" });
  return subirDocumento(archivo, persistido.memoria);
}
