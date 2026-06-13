import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Session } from "@supabase/supabase-js";
import { motion } from "framer-motion";
import { BookOpenCheck, FileSearch, Layers, ListChecks, Loader2 } from "lucide-react";

import AnalisisPanel from "@/components/chat/AnalisisPanel";
import ChatInput from "@/components/chat/ChatInput";
import FondoLiquido from "@/components/chat/FondoLiquido";
import MessageBubble from "@/components/chat/MessageBubble";
import ProgressTimeline from "@/components/chat/ProgressTimeline";
import Sidebar from "@/components/chat/Sidebar";
import UploadZone from "@/components/chat/UploadZone";
import { Button } from "@/components/ui/button";
import {
  cancelarRun,
  enviarChat,
  streamRun,
  subirDocumento,
  subirRubrica,
  type ChatFlags,
  type DocMemoria,
  type DocumentoInfo,
  type EventoRun,
} from "@/lib/api";
import {
  borrarPdfDeStorage,
  guardarDocEnConversacion,
  guardarMemoria,
  guardarPdfEnStorage,
  leerDocPersistido,
  memoriaVacia,
  rehidratar,
  type DocPersistido,
} from "@/lib/sesion";
import { supabase } from "@/lib/supabase";
import type { AccionMensaje, AnalisisDetalle, Conversacion, Mensaje, PasoProgreso } from "@/types";

let _id = 0;
const nuevoId = () => `m${Date.now()}_${_id++}`;

const QUICK_ACTIONS = [
  { icono: ListChecks, label: "Revisar todo el proyecto", prompt: "Revisa todo mi proyecto de tesis y dime sus puntos débiles" },
  { icono: FileSearch, label: "Revisar objetivos", prompt: "Revisa mis objetivos de investigación" },
  { icono: Layers, label: "Revisar metodología", prompt: "Revisa mi marco metodológico" },
  { icono: BookOpenCheck, label: "Revisar marco teórico", prompt: "Revisa mi marco teórico" },
];

const MAX_TURNOS_HISTORIAL = 12;

export default function Chat({ session }: { session: Session | null }) {
  const navigate = useNavigate();
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [conversaciones, setConversaciones] = useState<Conversacion[]>([]);
  const [convActiva, setConvActiva] = useState<string | null>(null);
  const [doc, setDoc] = useState<DocumentoInfo | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [etapaSubida, setEtapaSubida] = useState("");
  const [archivoPendiente, setArchivoPendiente] = useState<File | null>(null);
  const [ejecutando, setEjecutando] = useState(false);
  const [pasos, setPasos] = useState<PasoProgreso[]>([]);
  const [iteraciones, setIteraciones] = useState(2);
  const [analisis, setAnalisis] = useState<AnalisisDetalle | null>(null);

  const runIdRef = useRef<string | null>(null);
  const pendienteRef = useRef<{ texto: string; flags: ChatFlags } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Sesión: doc persistido pendiente de re-indexar + memoria del hilo (texto corregido)
  const docPersistidoRef = useRef<DocPersistido | null>(null);
  const docMemoriaRef = useRef<DocMemoria>(memoriaVacia());
  const mensajesRef = useRef<Mensaje[]>([]);
  mensajesRef.current = mensajes;

  const userId = session?.user.id ?? null;

  // ── Persistencia en Supabase ────────────────────────────────────────────────
  const cargarConversaciones = useCallback(async () => {
    if (!supabase || !session) return;
    const { data } = await supabase
      .from("conversaciones")
      .select("id, titulo, creada_en")
      .order("creada_en", { ascending: false });
    setConversaciones((data as Conversacion[]) ?? []);
  }, [session]);

  useEffect(() => {
    cargarConversaciones();
  }, [cargarConversaciones]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [mensajes, pasos]);

  async function asegurarConversacion(primerMensaje: string): Promise<string | null> {
    if (!supabase || !session) return null;
    if (convActiva) return convActiva;
    const titulo = primerMensaje.slice(0, 60) || "Nueva asesoría";
    const { data, error } = await supabase
      .from("conversaciones")
      .insert({ titulo, user_id: session.user.id })
      .select("id")
      .single();
    if (error || !data) return null;
    setConvActiva(data.id);
    cargarConversaciones();
    return data.id;
  }

  async function guardarMensaje(convId: string | null, m: Mensaje) {
    if (!supabase || !convId) return;
    const metadata: Record<string, unknown> = {};
    if (m.estructura) metadata.estructura = m.estructura;
    if (m.detalles?.length) metadata.detalles = m.detalles;
    await supabase.from("mensajes").insert({
      conversacion_id: convId,
      rol: m.rol,
      contenido: m.contenido,
      tipo: m.tipo ?? "texto",
      metadata,
    });
  }

  async function seleccionarConversacion(id: string) {
    if (!supabase || ejecutando) return;
    setConvActiva(id);
    setAnalisis(null);
    setDoc(null);

    const { data } = await supabase
      .from("mensajes")
      .select("rol, contenido, tipo, metadata")
      .eq("conversacion_id", id)
      .order("creado_en", { ascending: true });
    const cargados: Mensaje[] = (data ?? []).map((r: any) => ({
      id: nuevoId(),
      rol: r.rol,
      contenido: r.contenido,
      tipo: r.tipo,
      estructura: r.metadata?.estructura,
      detalles: r.metadata?.detalles,
    }));
    setMensajes(cargados);
    setPasos([]);

    // Restaurar la sesión: el PDF se re-indexa de forma diferida al primer mensaje.
    const persistido = await leerDocPersistido(id);
    docPersistidoRef.current = persistido;
    docMemoriaRef.current = persistido?.memoria ?? memoriaVacia();
  }

  async function eliminarConversacion(id: string) {
    if (!supabase) return;
    const persistido = await leerDocPersistido(id);
    await borrarPdfDeStorage(persistido?.storagePath ?? null);
    await supabase.from("conversaciones").delete().eq("id", id);
    if (id === convActiva) nuevaAsesoria();
    cargarConversaciones();
  }

  function nuevaAsesoria() {
    if (ejecutando) return;
    setConvActiva(null);
    setMensajes([]);
    setDoc(null);
    setPasos([]);
    setAnalisis(null);
    pendienteRef.current = null;
    docPersistidoRef.current = null;
    docMemoriaRef.current = memoriaVacia();
  }

  function agregarMensaje(m: Mensaje, convId?: string | null) {
    setMensajes((prev) => [...prev, m]);
    guardarMensaje(convId ?? convActiva, m);
  }

  // ── Subida / reemplazo del PDF de tesis ──────────────────────────────────────
  async function subirTesis(archivo: File) {
    setSubiendo(true);
    setEtapaSubida("Extrayendo texto y detectando la estructura…");
    const timer = setTimeout(
      () => setEtapaSubida("Generando embeddings y construyendo el índice RAG…"),
      3500,
    );
    try {
      // PDF nuevo = empieza de cero la memoria del hilo
      docMemoriaRef.current = memoriaVacia();
      docPersistidoRef.current = null;

      const info = await subirDocumento(archivo);
      setDoc(info);

      const convId = await asegurarConversacion(`Asesoría — ${info.nombre}`);

      // Persistir: PDF en Storage + metadata en la conversación
      let storagePath: string | null = null;
      if (convId && userId) {
        storagePath = await guardarPdfEnStorage(userId, convId, archivo);
        await guardarDocEnConversacion(convId, info, storagePath, docMemoriaRef.current);
      }

      agregarMensaje(
        {
          id: nuevoId(),
          rol: "assistant",
          tipo: "estructura",
          contenido: `Indexé **${info.nombre}**: ${info.stats.length} secciones.`,
          estructura: {
            nombre: info.nombre,
            stats: info.stats,
            estructura_toc: info.estructura_toc,
          },
        },
        convId,
      );
      agregarMensaje(
        {
          id: nuevoId(),
          rol: "assistant",
          contenido:
            "Tu proyecto está indexado y se quedará en este chat. Pregúntame dudas " +
            "metodológicas o pídeme una revisión: una sección («revisa mis objetivos») " +
            "o **todo el proyecto** para detectar sus puntos débiles.",
        },
        convId,
      );
    } catch (exc) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `⚠️ No pude procesar el PDF: ${exc instanceof Error ? exc.message : exc}`,
      });
    } finally {
      clearTimeout(timer);
      setSubiendo(false);
    }
  }

  /** Garantiza un documento vivo en el backend (re-indexa si el chat se reabrió). */
  async function asegurarDocVivo(): Promise<DocumentoInfo | null> {
    if (doc) return doc;
    const persistido = docPersistidoRef.current;
    if (!persistido) return null;
    setEtapaSubida("Reanudando tu proyecto…");
    setSubiendo(true);
    try {
      const info = await rehidratar(persistido);
      if (info) {
        setDoc(info);
        docPersistidoRef.current = null;
      }
      return info;
    } finally {
      setSubiendo(false);
    }
  }

  async function subirRubricaPdf(archivo: File) {
    const vivo = await asegurarDocVivo();
    if (!vivo) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: "⚠️ Primero necesito tu proyecto de tesis para asociar la rúbrica.",
      });
      return;
    }
    setSubiendo(true);
    setEtapaSubida("Parseando la rúbrica…");
    try {
      const r = await subirRubrica(vivo.doc_id, archivo);
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `Rúbrica **${r.nombre}** cargada: ${r.total_items} ítems en ${r.secciones} secciones (máx. ${r.puntaje_maximo} pts). La usaré en lugar de la rúbrica UPAO.`,
      });
    } catch (exc) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `⚠️ ${exc instanceof Error ? exc.message : exc}`,
      });
    } finally {
      setSubiendo(false);
    }
  }

  function manejarArchivo(archivo: File) {
    // Si ya hay proyecto (vivo o persistido) preguntamos qué es el PDF nuevo
    if (doc || docPersistidoRef.current) {
      setArchivoPendiente(archivo);
    } else {
      subirTesis(archivo);
    }
  }

  // ── Memoria del hilo (texto corregido) ──────────────────────────────────────
  function persistirMemoria() {
    if (convActiva) guardarMemoria(convActiva, docMemoriaRef.current);
  }

  function registrarDetalles(detalles?: AnalisisDetalle[]) {
    if (!detalles?.length) return;
    const m = docMemoriaRef.current;
    for (const d of detalles) {
      if (d.seccion && !m.evaluadas.includes(d.seccion)) m.evaluadas.push(d.seccion);
      if (d.seccion && d.texto_mejorado && !(d.seccion in m.aplicadas)) {
        m.pendientes[d.seccion] = d.texto_mejorado;
      }
    }
    persistirMemoria();
  }

  function incorporarMejoras(secciones?: string[]) {
    if (!secciones?.length) return;
    const m = docMemoriaRef.current;
    for (const s of secciones) {
      if (m.pendientes[s]) {
        m.aplicadas[s] = m.pendientes[s];
        delete m.pendientes[s];
      }
    }
    persistirMemoria();
  }

  // ── Eventos SSE → timeline ─────────────────────────────────────────────────
  function aplicarEvento(
    e: EventoRun,
    finalizar: (informe?: string, detalles?: AnalisisDetalle[]) => void,
  ) {
    setPasos((prev) => {
      const completados = prev.map((p) => ({ ...p, estado: "completado" as const }));
      const pushActivo = (texto: string) => [
        ...completados,
        { id: prev.length, texto, estado: "activo" as const },
      ];
      const pushCompletado = (texto: string) => [
        ...completados,
        { id: prev.length, texto, estado: "completado" as const },
      ];

      switch (e.tipo) {
        case "fase":
        case "progreso":
          return pushActivo(String(e.detalle ?? ""));
        case "nodo":
          return pushCompletado(`${e.label} completado`);
        case "diagnostico":
          return pushCompletado(`${e.capitulo} analizado — ${e.puntaje}/10`);
        default:
          return prev;
      }
    });

    if (e.tipo === "resultado") {
      finalizar(String(e.informe_md ?? ""), (e.detalles as AnalisisDetalle[]) ?? []);
    }
    if (e.tipo === "cancelado") {
      finalizar("⏹️ Revisión detenida. Lo avanzado no se perdió: pídeme continuar cuando quieras.");
    }
    if (e.tipo === "error") {
      finalizar(`⚠️ Ocurrió un error durante la revisión: ${e.detalle}`);
    }
  }

  // ── Confirmaciones de la memoria del hilo ──────────────────────────────────
  function accionesPara(subtipo: string): AccionMensaje[] {
    if (subtipo === "reevaluar") {
      return [
        { label: "Sí, evaluar de nuevo", flags: { confirmar_reevaluacion: true } },
        { label: "Cancelar", variante: "secundaria", flags: null },
      ];
    }
    return [
      { label: "Sí, usar el texto corregido", flags: { decision_mejoras: "aplicar" } },
      { label: "No, mantener el original", variante: "secundaria", flags: { decision_mejoras: "mantener" } },
    ];
  }

  function manejarAccion(mensajeId: string, flags: AccionMensaje["flags"]) {
    setMensajes((prev) =>
      prev.map((m) => (m.id === mensajeId ? { ...m, acciones: undefined } : m)),
    );
    const pendiente = pendienteRef.current;
    if (flags === null || !pendiente) {
      pendienteRef.current = null;
      return;
    }
    const combinados = { ...pendiente.flags, ...flags };
    pendienteRef.current = { texto: pendiente.texto, flags: combinados };
    procesarMensaje(pendiente.texto, combinados, { reenvio: true });
  }

  // ── Envío de mensajes ───────────────────────────────────────────────────────
  function construirHistorial(): { rol: string; contenido: string }[] {
    return mensajesRef.current
      .filter((m) => m.tipo !== "estructura" && m.contenido.trim())
      .slice(-MAX_TURNOS_HISTORIAL)
      .map((m) => ({ rol: m.rol, contenido: m.contenido.slice(0, 2000) }));
  }

  function enviarMensaje(texto: string) {
    pendienteRef.current = { texto, flags: {} };
    procesarMensaje(texto, {}, { reenvio: false });
  }

  async function procesarMensaje(
    texto: string,
    flags: ChatFlags,
    opts: { reenvio: boolean },
  ) {
    const convId = await asegurarConversacion(texto);
    if (!opts.reenvio) {
      agregarMensaje({ id: nuevoId(), rol: "user", contenido: texto }, convId);
    }

    // Historial ANTES de añadir nada nuevo del lado del asistente
    const historial = construirHistorial();

    // Re-indexar el proyecto si el chat se reabrió desde el historial
    let docActivo = doc;
    if (!docActivo && docPersistidoRef.current) {
      docActivo = await asegurarDocVivo();
    }

    const ultimoInforme =
      [...mensajesRef.current]
        .reverse()
        .find((m) => m.rol === "assistant" && m.tipo !== "estructura")?.contenido ?? "";

    setEjecutando(true);
    setPasos([]);
    try {
      const resp = await enviarChat({
        mensaje: texto,
        doc_id: docActivo?.doc_id ?? null,
        max_iteraciones: iteraciones,
        contexto_previo: ultimoInforme.slice(0, 6000),
        historial,
        ...flags,
      });

      if (resp.tipo === "conversacion") {
        agregarMensaje(
          { id: nuevoId(), rol: "assistant", contenido: resp.respuesta ?? "" },
          convId,
        );
        setEjecutando(false);
        pendienteRef.current = null;
        return;
      }

      if (resp.tipo === "confirmacion") {
        agregarMensaje(
          {
            id: nuevoId(),
            rol: "assistant",
            contenido: resp.mensaje ?? "¿Continuar?",
            acciones: accionesPara(resp.subtipo ?? ""),
          },
          convId,
        );
        setEjecutando(false);
        return;
      }

      if (resp.mejoras_aplicadas && resp.mejoras_aplicadas.length > 0) {
        incorporarMejoras(resp.mejoras_aplicadas);
        agregarMensaje(
          {
            id: nuevoId(),
            rol: "assistant",
            contenido:
              "✅ Incorporé el texto corregido de " +
              resp.mejoras_aplicadas.map((s) => `**${s}**`).join(", ") +
              " a mi memoria. Las próximas revisiones usarán esa versión.",
          },
          convId,
        );
      }

      runIdRef.current = resp.run_id!;
      let terminado = false;
      const finalizar = (informe?: string, detalles?: AnalisisDetalle[]) => {
        if (terminado) return;
        terminado = true;
        registrarDetalles(detalles);
        if (informe) {
          agregarMensaje(
            {
              id: nuevoId(),
              rol: "assistant",
              contenido: informe,
              detalles: detalles && detalles.length > 0 ? detalles : undefined,
            },
            convId,
          );
        }
      };

      await streamRun(resp.run_id!, (e) => aplicarEvento(e, finalizar));
      if (!terminado) {
        finalizar("⚠️ La conexión con el servidor se interrumpió antes de terminar.");
      }
      pendienteRef.current = null;
    } catch (exc) {
      agregarMensaje(
        {
          id: nuevoId(),
          rol: "assistant",
          contenido: `⚠️ ${exc instanceof Error ? exc.message : exc}`,
        },
        convId,
      );
    } finally {
      setEjecutando(false);
      setPasos([]);
      runIdRef.current = null;
    }
  }

  async function detener() {
    if (runIdRef.current) {
      try {
        await cancelarRun(runIdRef.current);
      } catch {
        /* el stream emitirá el evento de cancelado */
      }
    }
  }

  async function logout() {
    await supabase?.auth.signOut();
    navigate("/");
  }

  const vacio = mensajes.length === 0;

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar
        email={session?.user.email ?? null}
        conversaciones={conversaciones}
        conversacionActiva={convActiva}
        onNueva={nuevaAsesoria}
        onSeleccionar={seleccionarConversacion}
        onEliminar={eliminarConversacion}
        onLogout={logout}
      />

      <main className="flex-1 flex flex-col relative">
        <FondoLiquido intenso={ejecutando} />

        {vacio ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6">
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center mb-8"
            >
              <h1 className="text-3xl font-semibold tracking-tight">
                ¿Qué revisamos hoy?
              </h1>
              <p className="mt-2 text-muted-foreground">
                Sube tu proyecto de tesis y la red de agentes lo descompondrá antes de empezar.
              </p>
            </motion.div>

            <div className="w-full max-w-2xl space-y-5">
              <UploadZone subiendo={subiendo} etapa={etapaSubida} onArchivo={manejarArchivo} />
              <ChatInput
                ejecutando={ejecutando}
                deshabilitado={subiendo}
                iteraciones={iteraciones}
                onIteraciones={setIteraciones}
                onEnviar={enviarMensaje}
                onDetener={detener}
                onArchivo={manejarArchivo}
              />
              <div className="flex items-center justify-center flex-wrap gap-2.5">
                {QUICK_ACTIONS.map((qa) => {
                  const Icono = qa.icono;
                  return (
                    <Button
                      key={qa.label}
                      variant="outline"
                      disabled={ejecutando || subiendo}
                      onClick={() => enviarMensaje(qa.prompt)}
                      className="rounded-full bg-card/60 text-[13px] h-9 gap-1.5"
                    >
                      <Icono className="w-3.5 h-3.5 text-primary" />
                      {qa.label}
                    </Button>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="flex-1 overflow-y-auto">
              <div className="mx-auto max-w-3xl px-5 py-8 space-y-5">
                {mensajes.map((m) => (
                  <MessageBubble
                    key={m.id}
                    mensaje={m}
                    onVerAnalisis={setAnalisis}
                    onAccion={manejarAccion}
                  />
                ))}

                {ejecutando && (
                  <div className="glass rounded-3xl px-5 py-4">
                    <ProgressTimeline pasos={pasos} />
                  </div>
                )}

                {subiendo && (
                  <div className="glass rounded-3xl px-5 py-4 text-sm text-muted-foreground flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin text-primary" />
                    {etapaSubida}
                  </div>
                )}
              </div>
            </div>

            <div className="px-5 pb-5">
              <div className="mx-auto max-w-3xl">
                {archivoPendiente && (
                  <div className="glass rounded-2xl px-4 py-3 mb-3 flex flex-wrap items-center gap-3 text-sm">
                    <span className="font-medium truncate">{archivoPendiente.name}</span>
                    <span className="text-muted-foreground">¿Qué es este PDF?</span>
                    <div className="flex gap-2 ml-auto">
                      <Button
                        size="sm"
                        variant="outline"
                        className="rounded-full"
                        onClick={() => {
                          subirRubricaPdf(archivoPendiente);
                          setArchivoPendiente(null);
                        }}
                      >
                        Rúbrica de mi jurado
                      </Button>
                      <Button
                        size="sm"
                        className="rounded-full"
                        onClick={() => {
                          subirTesis(archivoPendiente);
                          setArchivoPendiente(null);
                        }}
                      >
                        Nueva versión de tesis
                      </Button>
                    </div>
                  </div>
                )}

                <ChatInput
                  ejecutando={ejecutando}
                  deshabilitado={subiendo}
                  iteraciones={iteraciones}
                  onIteraciones={setIteraciones}
                  onEnviar={enviarMensaje}
                  onDetener={detener}
                  onArchivo={manejarArchivo}
                />
                <p className="mt-2 text-center text-[11px] text-muted-foreground">
                  Los agentes pueden equivocarse — valida las sugerencias con tu asesor.
                </p>
              </div>
            </div>
          </>
        )}

        {analisis && <AnalisisPanel detalle={analisis} onCerrar={() => setAnalisis(null)} />}
      </main>
    </div>
  );
}
