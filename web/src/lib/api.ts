import { supabase } from "./supabase";

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || "";

export interface SeccionStat {
  seccion: string;
  pagina_inicio: number;
  chars: number;
  n_fragmentos: number;
  mejorado?: boolean;
}

export interface DocumentoInfo {
  doc_id: string;
  nombre: string;
  hash: string;
  ya_indexado: boolean;
  estructura_toc: Record<string, number>;
  stats: SeccionStat[];
  rubrica: { nombre: string; total_items: number; puntaje_maximo: number } | null;
}

export interface ChatRespuesta {
  tipo: "conversacion" | "run" | "confirmacion";
  respuesta?: string;
  run_id?: string;
  modo?: "completo" | "secciones";
  secciones?: string[];
  subtipo?: "reevaluar" | "aplicar_mejoras";
  mensaje?: string;
  mejoras_aplicadas?: string[];
}

export interface ChatFlags {
  confirmar_reevaluacion?: boolean;
  decision_mejoras?: "aplicar" | "mantener";
}

export interface EventoRun {
  tipo: string;
  [key: string]: unknown;
}

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {};
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function manejarError(res: Response): Promise<never> {
  let detalle = `Error ${res.status}`;
  try {
    const body = await res.json();
    detalle = body.detail || detalle;
  } catch {
    /* respuesta sin JSON */
  }
  throw new Error(detalle);
}

export interface DocMemoria {
  evaluadas: string[];
  aplicadas: Record<string, string>;
  pendientes: Record<string, string>;
}

export async function subirDocumento(
  archivo: File,
  memoria?: DocMemoria | null,
): Promise<DocumentoInfo> {
  const form = new FormData();
  form.append("archivo", archivo);
  if (memoria) form.append("memoria", JSON.stringify(memoria));
  const res = await fetch(`${API_URL}/api/documentos`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  if (!res.ok) await manejarError(res);
  return res.json();
}

export async function subirRubrica(docId: string, archivo: File) {
  const form = new FormData();
  form.append("archivo", archivo);
  const res = await fetch(`${API_URL}/api/documentos/${docId}/rubrica`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  if (!res.ok) await manejarError(res);
  return res.json();
}

export async function obtenerBiblioteca(): Promise<{
  libros: { nombre: string; fragmentos: number }[];
  total_fragmentos: number;
}> {
  const res = await fetch(`${API_URL}/api/biblioteca`, {
    headers: await authHeaders(),
  });
  if (!res.ok) await manejarError(res);
  return res.json();
}

export async function enviarChat(body: {
  mensaje: string;
  doc_id: string | null;
  max_iteraciones: number;
  contexto_previo: string;
  historial?: { rol: string; contenido: string }[];
} & ChatFlags): Promise<ChatRespuesta> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) await manejarError(res);
  return res.json();
}

export async function cancelarRun(runId: string) {
  const res = await fetch(`${API_URL}/api/runs/${runId}/cancelar`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok) await manejarError(res);
  return res.json();
}

export async function streamRun(
  runId: string,
  onEvento: (e: EventoRun) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/runs/${runId}/stream`, {
    headers: await authHeaders(),
    signal,
  });
  if (!res.ok || !res.body) await manejarError(res);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const bloques = buffer.split("\n\n");
    buffer = bloques.pop() ?? "";
    for (const bloque of bloques) {
      const linea = bloque.split("\n").find((l) => l.startsWith("data: "));
      if (!linea) continue;
      try {
        onEvento(JSON.parse(linea.slice(6)) as EventoRun);
      } catch {
        /* evento malformado: ignorar */
      }
    }
  }
}
