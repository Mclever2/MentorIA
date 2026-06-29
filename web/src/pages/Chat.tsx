import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Session } from "@supabase/supabase-js";
import { motion } from "framer-motion";
import { BookOpenCheck, FileSearch, Layers, ListChecks, Loader2, Menu } from "lucide-react";

import AnalisisPanel from "@/components/chat/AnalisisPanel";
import RevisionCompletaPanel from "@/components/chat/RevisionCompletaPanel";
import ChatInput from "@/components/chat/ChatInput";
import FondoLiquido from "@/components/chat/FondoLiquido";
import MessageBubble from "@/components/chat/MessageBubble";
import PerfilModal from "@/components/chat/PerfilModal";
import ProgressTimeline from "@/components/chat/ProgressTimeline";
import RecursosPanel from "@/components/chat/RecursosPanel";
import RubricaTabla from "@/components/chat/RubricaTabla";
import Sidebar from "@/components/chat/Sidebar";
import UploadZone from "@/components/chat/UploadZone";
import { Button } from "@/components/ui/button";
import {
  buscarUniversidad,
  cancelarRun,
  enviarChat,
  setRecursosDoc,
  streamRun,
  subirDocumento,
  subirReglamento,
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
import {
  guardarPreferencias,
  guardarRecursosConversacion,
  leerPreferencias,
  leerRecursosConversacion,
  recursosVacios,
} from "@/lib/recursos";
import { supabase } from "@/lib/supabase";
import type {
  AccionMensaje,
  AnalisisDetalle,
  Conversacion,
  Mensaje,
  PasoProgreso,
  PerfilUniversidad,
  RevisionCompleta,
  RubricaPersist,
} from "@/types";

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
  const [iteraciones, setIteraciones] = useState(1);
  const [analisis, setAnalisis] = useState<AnalisisDetalle | null>(null);
  const [revPanel, setRevPanel] = useState<RevisionCompleta | null>(null);
  const [navAbierto, setNavAbierto] = useState(false); // cajón del sidebar en móvil

  // Rúbrica + perfil de universidad (snapshot por chat, default del usuario)
  const [rubrica, setRubrica] = useState<RubricaPersist | null>(null);
  const [perfil, setPerfil] = useState<PerfilUniversidad | null>(null);
  const [cargandoRubrica, setCargandoRubrica] = useState(false);
  const [cargandoPerfil, setCargandoPerfil] = useState(false);
  const [estadoRubrica, setEstadoRubrica] = useState("");
  const [estadoPerfil, setEstadoPerfil] = useState("");
  const [verRubrica, setVerRubrica] = useState(false);
  const [verPerfil, setVerPerfil] = useState(false);
  // Hay proyecto cargado o persistido (rehidratable) → habilita subir rúbrica.
  const [proyectoDisponible, setProyectoDisponible] = useState(false);

  const runIdRef = useRef<string | null>(null);
  const pendienteRef = useRef<{ texto: string; flags: ChatFlags } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Sesión: doc persistido pendiente de re-indexar + memoria del hilo (texto corregido)
  const docPersistidoRef = useRef<DocPersistido | null>(null);
  const docMemoriaRef = useRef<DocMemoria>(memoriaVacia());
  const mensajesRef = useRef<Mensaje[]>([]);
  mensajesRef.current = mensajes;
  // Refs sincronizados para closures asíncronos + default del usuario
  const rubricaRef = useRef<RubricaPersist | null>(null);
  const perfilRef = useRef<PerfilUniversidad | null>(null);
  rubricaRef.current = rubrica;
  perfilRef.current = perfil;
  const preferenciasRef = useRef(recursosVacios());

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

  // Default del usuario (rúbrica + perfil) que heredan los chats nuevos.
  useEffect(() => {
    if (!session) return;
    leerPreferencias().then((p) => {
      preferenciasRef.current = p;
      if (!convActiva) {
        setRubrica(p.rubrica);
        setPerfil(p.perfil);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

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
    // Congela en el chat la rúbrica/perfil activos al momento de crearlo.
    guardarRecursosConversacion(data.id, {
      rubrica: rubricaRef.current,
      perfil: perfilRef.current,
    });
    cargarConversaciones();
    return data.id;
  }

  async function guardarMensaje(convId: string | null, m: Mensaje) {
    if (!supabase || !convId) return;
    const metadata: Record<string, unknown> = {};
    if (m.estructura) metadata.estructura = m.estructura;
    if (m.detalles?.length) metadata.detalles = m.detalles;
    if (m.revision) metadata.revision = m.revision;
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
    setRevPanel(null);
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
      revision: r.metadata?.revision,
    }));
    setMensajes(cargados);
    setPasos([]);

    // Restaurar la sesión: el PDF se re-indexa de forma diferida al primer mensaje.
    const persistido = await leerDocPersistido(id);
    docPersistidoRef.current = persistido;
    docMemoriaRef.current = persistido?.memoria ?? memoriaVacia();
    setProyectoDisponible(persistido !== null);

    // Cargar el snapshot de rúbrica/perfil de ESTE chat (respeta lo que usó).
    const rec = await leerRecursosConversacion(id);
    setRubrica(rec.rubrica);
    setPerfil(rec.perfil);
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
    setRevPanel(null);
    pendienteRef.current = null;
    docPersistidoRef.current = null;
    docMemoriaRef.current = memoriaVacia();
    setProyectoDisponible(false);
    // Un chat nuevo hereda el default del usuario.
    setRubrica(preferenciasRef.current.rubrica);
    setPerfil(preferenciasRef.current.perfil);
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

      const info = await subirDocumento(archivo, null, rubricaRef.current, perfilRef.current);
      setDoc(info);
      setProyectoDisponible(true);
      sincronizarRubricaMapeada(info);

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
        setProyectoDisponible(true);
        sincronizarRubricaMapeada(info);
        docPersistidoRef.current = null;
      }
      return info;
    } finally {
      setSubiendo(false);
    }
  }

  // ── Recursos del navbar: rúbrica + perfil de universidad ────────────────────
  /** Persiste rúbrica/perfil actuales como default del usuario y snapshot del chat. */
  async function guardarRecursosActuales() {
    const r = { rubrica: rubricaRef.current, perfil: perfilRef.current };
    preferenciasRef.current = r;
    if (userId) await guardarPreferencias(userId, r);
    if (convActiva) await guardarRecursosConversacion(convActiva, r);
  }

  /** Tras indexar el proyecto, el backend devuelve la rúbrica ya mapeada: la re-persiste. */
  function sincronizarRubricaMapeada(info: DocumentoInfo) {
    const full = info.rubrica_full;
    const tieneMapa = !!full?.mapa_secciones && Object.keys(full.mapa_secciones).length > 0;
    const yaMapeada =
      !!rubricaRef.current?.mapa_secciones &&
      Object.keys(rubricaRef.current.mapa_secciones).length > 0;
    if (full && tieneMapa && !yaMapeada) {
      setRubrica(full);
      rubricaRef.current = full;
      void guardarRecursosActuales();
    }
  }

  async function onSubirRubrica(archivo: File) {
    const vivo = await asegurarDocVivo();
    if (!vivo) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: "⚠️ Primero sube tu proyecto de tesis: la rúbrica se mapea a sus secciones al cargarla.",
      });
      return;
    }
    setCargandoRubrica(true);
    setEstadoRubrica("Transformando y mapeando la rúbrica a tus secciones…");
    try {
      const r = await subirRubrica(vivo.doc_id, archivo);
      setRubrica(r.rubrica);
      rubricaRef.current = r.rubrica;
      await guardarRecursosActuales();
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `Rúbrica **${r.nombre}** cargada: ${r.total_items} ítems · ${r.secciones_mapeadas} secciones mapeadas`
          + (r.items_ausentes ? ` · ${r.items_ausentes} criterio(s) que tu proyecto aún no cubre` : "")
          + ` (máx. ${r.puntaje_maximo} pts). La usaré en lugar de la UPAO.`,
      });
    } catch (exc) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `⚠️ ${exc instanceof Error ? exc.message : exc}`,
      });
    } finally {
      setCargandoRubrica(false);
      setEstadoRubrica("");
    }
  }

  async function onEliminarRubrica() {
    setRubrica(null);
    rubricaRef.current = null;
    await guardarRecursosActuales();
    if (doc) {
      try {
        await setRecursosDoc(doc.doc_id, { limpiar_rubrica: true });
      } catch {
        /* el doc puede haberse reiniciado; se aplicará al rehidratar */
      }
    }
  }

  async function onBuscarUniversidad(universidad: string, nivel: string) {
    if (!universidad) return;
    setCargandoPerfil(true);
    setEstadoPerfil(`Buscando reglamentos de ${universidad}…`);
    try {
      const res = await buscarUniversidad(universidad, "ingeniería de sistemas", nivel);
      if (res.encontrado && res.perfil) {
        await aplicarPerfil(res.perfil);
        const aviso = res.perfil.advertencia ? `\n\n⚠️ ${res.perfil.advertencia}` : "";
        agregarMensaje({
          id: nuevoId(),
          rol: "assistant",
          contenido: `Encontré los lineamientos de **${res.perfil.universidad}** (${res.perfil.nivel}). Los agentes adaptarán su criterio a esta universidad en este chat.${aviso}`,
        });
      } else {
        agregarMensaje({
          id: nuevoId(),
          rol: "assistant",
          contenido: `${res.motivo ?? `No encontré reglamentos públicos de **${universidad}**.`} Súbelos manualmente con el botón **Subir** del panel.`,
        });
      }
    } catch (exc) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `⚠️ ${exc instanceof Error ? exc.message : exc}`,
      });
    } finally {
      setCargandoPerfil(false);
      setEstadoPerfil("");
    }
  }

  async function onSubirReglamento(archivo: File, universidad: string, nivel: string) {
    if (!universidad) return;
    setCargandoPerfil(true);
    setEstadoPerfil("Procesando el reglamento…");
    try {
      const { perfil: p } = await subirReglamento(archivo, universidad, "ingeniería de sistemas", nivel);
      await aplicarPerfil(p);
      const aviso = p.advertencia ? `\n\n⚠️ ${p.advertencia}` : "";
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `Reglamento de **${p.universidad}** cargado. Los agentes ajustarán su personalidad a estos lineamientos.${aviso}`,
      });
    } catch (exc) {
      agregarMensaje({
        id: nuevoId(),
        rol: "assistant",
        contenido: `⚠️ ${exc instanceof Error ? exc.message : exc}`,
      });
    } finally {
      setCargandoPerfil(false);
      setEstadoPerfil("");
    }
  }

  async function aplicarPerfil(p: PerfilUniversidad) {
    setPerfil(p);
    perfilRef.current = p;
    await guardarRecursosActuales();
    if (doc) {
      try {
        await setRecursosDoc(doc.doc_id, { perfil_universidad: p });
      } catch {
        /* se aplicará al rehidratar */
      }
    }
  }

  async function onEliminarPerfil() {
    setPerfil(null);
    perfilRef.current = null;
    await guardarRecursosActuales();
    if (doc) {
      try {
        await setRecursosDoc(doc.doc_id, { limpiar_perfil: true });
      } catch {
        /* se aplicará al rehidratar */
      }
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
    finalizar: (informe?: string, detalles?: AnalisisDetalle[], revision?: RevisionCompleta) => void,
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
          return pushCompletado(`${e.capitulo} calificado`);
        default:
          return prev;
      }
    });

    if (e.tipo === "resultado") {
      if (e.resumen_chat) {
        docMemoriaRef.current.ultima_revision =
          e.resumen_chat as DocMemoria["ultima_revision"];
      }
      const rev = e.calificacion
        ? ({
            calificacion: e.calificacion as RevisionCompleta["calificacion"],
            fortalezas: e.fortalezas as string[] | undefined,
            debilidades: e.debilidades as string[] | undefined,
            trazabilidad: e.trazabilidad as RevisionCompleta["trazabilidad"],
          } as RevisionCompleta)
        : undefined;
      finalizar(String(e.informe_md ?? ""), (e.detalles as AnalisisDetalle[]) ?? [], rev);
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
      const finalizar = (
        informe?: string,
        detalles?: AnalisisDetalle[],
        revision?: RevisionCompleta,
      ) => {
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
              revision,
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
        abierto={navAbierto}
        onCerrar={() => setNavAbierto(false)}
        email={session?.user.email ?? null}
        conversaciones={conversaciones}
        conversacionActiva={convActiva}
        onNueva={nuevaAsesoria}
        onSeleccionar={seleccionarConversacion}
        onEliminar={eliminarConversacion}
        onLogout={logout}
        recursosSlot={
          <RecursosPanel
            rubrica={rubrica}
            perfil={perfil}
            hayProyecto={!!doc || proyectoDisponible}
            cargandoRubrica={cargandoRubrica}
            cargandoPerfil={cargandoPerfil}
            estadoRubrica={estadoRubrica}
            estadoPerfil={estadoPerfil}
            onSubirRubrica={onSubirRubrica}
            onEliminarRubrica={onEliminarRubrica}
            onVerRubrica={() => setVerRubrica(true)}
            onBuscarUniversidad={onBuscarUniversidad}
            onSubirReglamento={onSubirReglamento}
            onEliminarPerfil={onEliminarPerfil}
            onVerPerfil={() => setVerPerfil(true)}
          />
        }
      />

      {navAbierto && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setNavAbierto(false)}
          aria-hidden
        />
      )}

      <main className="flex-1 flex flex-col relative">
        <FondoLiquido intenso={ejecutando} />

        <div className="md:hidden flex items-center gap-2 px-4 h-14 shrink-0 border-b border-border bg-card/60 backdrop-blur-xl z-10">
          <button
            onClick={() => setNavAbierto(true)}
            className="p-2 -ml-2 rounded-xl hover:bg-muted"
            aria-label="Abrir menú"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="font-semibold">MentorIA</span>
        </div>

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
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    Rúbrica: <span className="font-medium text-foreground/80">{rubrica ? rubrica.nombre : "UPAO (por defecto)"}</span>
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    Reglamento: <span className="font-medium text-foreground/80">{perfil ? perfil.universidad : "criterio base"}</span>
                  </span>
                </div>
                {mensajes.map((m) => (
                  <MessageBubble
                    key={m.id}
                    mensaje={m}
                    onVerAnalisis={setAnalisis}
                    onVerRevision={setRevPanel}
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
                          onSubirRubrica(archivoPendiente);
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
        {revPanel && <RevisionCompletaPanel revision={revPanel} onCerrar={() => setRevPanel(null)} />}
        {verRubrica && rubrica && (
          <RubricaTabla rubrica={rubrica} onCerrar={() => setVerRubrica(false)} />
        )}
        {verPerfil && perfil && (
          <PerfilModal perfil={perfil} onCerrar={() => setVerPerfil(false)} />
        )}
      </main>
    </div>
  );
}
