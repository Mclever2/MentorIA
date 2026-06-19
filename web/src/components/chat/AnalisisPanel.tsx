import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  ClipboardCheck,
  FileText,
  Gauge,
  Globe,
  Handshake,
  Landmark,
  Lightbulb,
  Link2,
  type LucideIcon,
  MessageCircle,
  Microscope,
  Scale,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AnalisisDetalle, ItemRubrica, SesionDebate } from "@/types";

type TabId = "evaluacion" | "rubrica" | "debate" | "fragmentos" | "metricas";

const TABS: { id: TabId; label: string }[] = [
  { id: "evaluacion", label: "Evaluación" },
  { id: "rubrica", label: "Rúbrica" },
  { id: "debate", label: "Debate" },
  { id: "fragmentos", label: "Fragmentos RAG" },
  { id: "metricas", label: "Métricas" },
];

export default function AnalisisPanel({
  detalle,
  onCerrar,
}: {
  detalle: AnalisisDetalle;
  onCerrar: () => void;
}) {
  const [tab, setTab] = useState<TabId>("evaluacion");

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="absolute inset-0 z-30 bg-background flex flex-col"
    >
      <div className="border-b border-border bg-card/60 backdrop-blur-xl">
        <div className="mx-auto max-w-4xl px-5 py-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" className="rounded-full" onClick={onCerrar}>
              <ArrowLeft className="w-5 h-5" />
            </Button>
            <div className="min-w-0">
              <h1 className="font-semibold text-lg truncate">{detalle.seccion}</h1>
              <p className="text-xs text-muted-foreground">
                Análisis completo de la red multiagente
                {detalle.iteraciones != null && ` · ${detalle.iteraciones} iteración(es)`}
              </p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Puntaje etiqueta="Inicial" valor={detalle.puntaje_inicial} max={detalle.puntaje_max} />
              <span className="text-muted-foreground">→</span>
              <Puntaje etiqueta="Final" valor={detalle.puntaje} max={detalle.puntaje_max} destacado />
            </div>
          </div>

          <div className="mt-4 bg-muted rounded-xl p-1 grid grid-cols-5 text-[13px] font-medium">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  "py-1.5 rounded-lg transition-all truncate px-1",
                  tab === t.id
                    ? "bg-card shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-5 py-6 space-y-5">
          {tab === "evaluacion" && <TabEvaluacion d={detalle} />}
          {tab === "rubrica" && <TabRubrica d={detalle} />}
          {tab === "debate" && <TabDebate d={detalle} />}
          {tab === "fragmentos" && <TabFragmentos d={detalle} />}
          {tab === "metricas" && <TabMetricas d={detalle} />}
        </div>
      </div>
    </motion.div>
  );
}


function Puntaje({
  etiqueta,
  valor,
  max,
  destacado,
}: {
  etiqueta: string;
  valor?: number | null;
  max?: number | null;
  destacado?: boolean;
}) {
  const ratio = valor != null && max ? valor / max : null;
  const color =
    ratio == null ? "text-muted-foreground"
    : ratio >= 0.8 ? "text-[#34C759]"
    : ratio >= 0.5 ? "text-[#FF9500]"
    : "text-destructive";
  return (
    <div className={cn("text-center rounded-2xl px-3 py-1.5", destacado && "glass")}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{etiqueta}</div>
      <div className={cn("font-semibold tabular-nums", color)}>
        {valor != null ? Math.round(valor) : "—"}
        {max ? `/${max}` : ""}
      </div>
    </div>
  );
}

function Tarjeta({
  icono,
  titulo,
  children,
}: {
  icono?: React.ReactNode;
  titulo: string;
  children: React.ReactNode;
}) {
  return (
    <section className="glass rounded-3xl p-5">
      <h2 className="font-semibold flex items-center gap-2 mb-3">
        {icono}
        {titulo}
      </h2>
      {children}
    </section>
  );
}

function Md({ texto }: { texto: string }) {
  return (
    <div className="prose-informe text-[14px]">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{texto}</ReactMarkdown>
    </div>
  );
}


function TabEvaluacion({ d }: { d: AnalisisDetalle }) {
  return (
    <>
      {d.texto_mejorado ? (
        <Tarjeta icono={<Sparkles className="w-4 h-4 text-primary" />} titulo="Texto final propuesto por el Redactor">
          <div className="bg-muted/60 rounded-2xl p-4 max-h-[28rem] overflow-y-auto">
            <Md texto={d.texto_mejorado} />
          </div>
          {d.texto_mejorado.includes("[COMPLETAR:") && (
            <p className="mt-2 text-xs text-[#FF9500] flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              El texto contiene marcas «[COMPLETAR: …]» que debes rellenar con contenido real.
            </p>
          )}
        </Tarjeta>
      ) : (
        <Tarjeta titulo="Texto final">
          <p className="text-sm text-muted-foreground">
            El texto fue evaluado sin reescritura automática.
          </p>
        </Tarjeta>
      )}

      {d.sugerencias_redactor && (
        <Tarjeta
          icono={<Lightbulb className="w-4 h-4 text-primary" />}
          titulo="Recomendaciones del Redactor (no se califican)"
        >
          <Md texto={d.sugerencias_redactor} />
        </Tarjeta>
      )}

      {d.feedback_auditor && (
        <Tarjeta icono={<ClipboardCheck className="w-4 h-4 text-primary" />} titulo="Feedback del Auditor">
          <Md texto={d.feedback_auditor} />
        </Tarjeta>
      )}

      {d.observaciones_metodologicas && (
        <Tarjeta titulo="Recomendaciones del Metodólogo">
          <Md texto={d.observaciones_metodologicas} />
        </Tarjeta>
      )}
    </>
  );
}


function FilaItem({ item, antes, escala }: { item: ItemRubrica; antes?: ItemRubrica; escala: number }) {
  const pts = item.puntaje ?? 0;
  const ptsAntes = antes?.puntaje;
  const max = item.maximo ?? escala;          // escala ponderada por ítem (juez /100) o 0-5
  const ratio = max > 0 ? pts / max : 0;
  const color = ratio >= 0.8 ? "text-[#34C759]" : ratio >= 0.5 ? "text-[#FF9500]" : "text-destructive";
  return (
    <li className="py-2.5 border-b border-border/60 last:border-0">
      <div className="flex items-start gap-3">
        <span className="shrink-0 w-8 h-8 rounded-xl bg-muted grid place-items-center text-xs font-semibold">
          {String(item.item_numero).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug">{item.criterio || item.descripcion}</p>
          {item.observacion && (
            <p className="mt-1 text-xs text-muted-foreground leading-snug">
              {ratio < 1 && (
                <span className="font-medium text-[#FF9500]">Para el máximo: </span>
              )}
              {item.observacion}
            </p>
          )}
        </div>
        <div className="shrink-0 text-right tabular-nums text-sm">
          {ptsAntes != null && (
            <span className="text-muted-foreground line-through mr-1.5">{ptsAntes}</span>
          )}
          <span className={cn("font-semibold", color)}>{pts}/{max}</span>
        </div>
      </div>
    </li>
  );
}

function TabRubrica({ d }: { d: AnalisisDetalle }) {
  const inicial = d.evaluacion_inicial ?? [];
  const final = d.evaluacion_final ?? [];
  const antesPorItem = new Map(inicial.map((i) => [i.item_numero, i]));
  const errores = d.errores_rubrica ?? [];
  const escala = d.escala_max ?? 5;

  return (
    <>
      {final.length > 0 ? (
        <Tarjeta titulo="Rúbrica — texto final (tachado: puntaje del texto original)">
          <ul>
            {final.map((it) => (
              <FilaItem key={it.item_numero} item={it} antes={antesPorItem.get(it.item_numero)} escala={escala} />
            ))}
          </ul>
        </Tarjeta>
      ) : inicial.length > 0 ? (
        <Tarjeta titulo="Rúbrica — evaluación del texto original">
          <ul>
            {inicial.map((it) => (
              <FilaItem key={it.item_numero} item={it} escala={escala} />
            ))}
          </ul>
        </Tarjeta>
      ) : null}

      <Tarjeta titulo={errores.length > 0 ? `Observaciones pendientes (${errores.length} ítems)` : "Observaciones"}>
        {errores.length > 0 ? (
          <ul className="space-y-2">
            {errores.map((e, i) => (
              <li key={i} className="text-[13px] flex gap-2">
                <span className="shrink-0 font-semibold text-destructive">
                  Ítem {String(e.item_numero).padStart(2, "0")}
                </span>
                <span>
                  (puntaje {e.puntaje_actual}): {e.descripcion}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[#34C759]">
            ✓ El texto cumple todos los ítems evaluados de la rúbrica.
          </p>
        )}
      </Tarjeta>
    </>
  );
}


const ICONO_SUBAGENTE: Record<string, LucideIcon> = {
  perspectiva_formal: Landmark,
  perspectiva_metodologica: Microscope,
  perspectiva_contextual: Globe,
  sintetizador_debate: Scale,
};

function Sesion({ s, idx }: { s: SesionDebate; idx: number }) {
  const v = s.veredicto ?? {};
  return (
    <Tarjeta
      icono={<Scale className="w-4 h-4 text-primary" />}
      titulo={`Sesión ${idx} — Veredicto: ${v.veredicto_general ?? "—"}`}
    >
      <p className="text-xs text-muted-foreground mb-3">
        ✓ confirmados: {JSON.stringify(v.items_confirmados ?? [])} · ✗ descartados:{" "}
        {JSON.stringify(v.items_descartados ?? [])} · ~ matizados:{" "}
        {JSON.stringify(v.items_matizados ?? [])}
      </p>
      {v.justificacion && <p className="text-[13px] mb-3 italic">{v.justificacion}</p>}
      <div className="space-y-3">
        {s.panel.map((p, i) => {
          const IconoSub = ICONO_SUBAGENTE[p.subagente] ?? MessageCircle;
          return (
            <div key={i} className="bg-muted/60 rounded-2xl p-3.5">
              <p className="text-[13px] font-semibold mb-1 flex items-center gap-1.5">
                <IconoSub className="w-3.5 h-3.5 text-primary shrink-0" />
                {p.subagente.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </p>
              <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{p.contenido}</p>
            </div>
          );
        })}
      </div>
    </Tarjeta>
  );
}

function TabDebate({ d }: { d: AnalisisDetalle }) {
  const sesiones = d.debate?.sesiones ?? [];
  return (
    <>
      {sesiones.length > 0 ? (
        sesiones.map((s, i) => <Sesion key={i} s={s} idx={i + 1} />)
      ) : (
        <Tarjeta titulo="Panel de debate">
          <p className="text-sm text-muted-foreground">
            No se realizaron sesiones de debate en esta evaluación. El panel de 4 subagentes solo se
            convoca cuando el auditor detecta <span className="font-medium text-foreground">errores de
            rúbrica</span> que consolidar o cuestionar. Aquí no se marcaron errores (la sección cumple
            los ítems evaluados), así que la red se ahorró esas llamadas.
          </p>
        </Tarjeta>
      )}

      <div className="grid sm:grid-cols-2 gap-5">
        <Tarjeta icono={<Handshake className="w-4 h-4 text-primary" />} titulo="Consenso">
          {d.consenso ? <Md texto={d.consenso} /> : <p className="text-sm text-muted-foreground">Sin análisis de consenso.</p>}
        </Tarjeta>
        <Tarjeta icono={<Zap className="w-4 h-4 text-primary" />} titulo="Disenso">
          {d.disenso ? <Md texto={d.disenso} /> : <p className="text-sm text-muted-foreground">Sin análisis de disenso.</p>}
        </Tarjeta>
      </div>
    </>
  );
}


function GrupoFragmentos({
  icono,
  titulo,
  texto,
  etiqueta,
}: {
  icono: React.ReactNode;
  titulo: string;
  texto?: string;
  etiqueta: string;
}) {
  const fragmentos = (texto ?? "")
    .split("---")
    .map((f) => f.trim())
    .filter(Boolean);

  return (
    <Tarjeta icono={icono} titulo={titulo}>
      {fragmentos.length === 0 ? (
        <p className="text-sm text-muted-foreground">No se recuperaron fragmentos.</p>
      ) : (
        <div className="space-y-2">
          {fragmentos.map((f, i) => (
            <details key={i} className="bg-muted/60 rounded-2xl overflow-hidden" open={i === 0}>
              <summary className="px-4 py-2.5 text-[13px] font-medium cursor-pointer select-none">
                {etiqueta} {i + 1}
              </summary>
              <pre className="whitespace-pre-wrap text-xs leading-relaxed font-sans px-4 pb-3 max-h-72 overflow-y-auto">
                {f}
              </pre>
            </details>
          ))}
        </div>
      )}
    </Tarjeta>
  );
}

function TabFragmentos({ d }: { d: AnalisisDetalle }) {
  return (
    <>
      <p className="text-xs text-muted-foreground -mb-1">
        Lo que la red de agentes recuperó vía RAG para fundamentar esta revisión.
      </p>
      <GrupoFragmentos
        icono={<FileText className="w-4 h-4 text-primary" />}
        titulo="Del PDF de tu tesis"
        texto={d.contexto_pdf}
        etiqueta="Fragmento"
      />
      <GrupoFragmentos
        icono={<BookOpen className="w-4 h-4 text-primary" />}
        titulo="De los libros de metodología"
        texto={d.contexto_teorico}
        etiqueta="Referencia"
      />
      <GrupoFragmentos
        icono={<Link2 className="w-4 h-4 text-primary" />}
        titulo="Contexto cruzado (otras secciones del proyecto)"
        texto={d.contexto_cruzado}
        etiqueta="Sección relacionada"
      />
    </>
  );
}


function Metrica({ nombre, valor, ayuda }: { nombre: string; valor: string; ayuda?: string }) {
  return (
    <div className="glass rounded-2xl p-4">
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{nombre}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{valor}</div>
      {ayuda && <div className="mt-1 text-[11px] text-muted-foreground leading-snug">{ayuda}</div>}
    </div>
  );
}

function TabMetricas({ d }: { d: AnalisisDetalle }) {
  const juez = d.metricas_juez;
  const m = (d.metricas ?? {}) as Record<string, any>;
  const hayMetricas = Object.keys(m).length > 0;

  if (!juez?.calificacion?.items?.length && !hayMetricas) {
    return (
      <Tarjeta icono={<Gauge className="w-4 h-4 text-primary" />} titulo="Métricas de proceso y calidad">
        <p className="text-sm text-muted-foreground">
          Las métricas no están disponibles para esta sesión.
        </p>
      </Tarjeta>
    );
  }

  const items: any[] = m.llm_judge_items ?? [];
  const trayectoria: any[] = m.iterative_consistency ?? [];

  return (
    <>
      {juez?.calificacion?.items?.length ? (
        <Tarjeta
          icono={<Gauge className="w-4 h-4 text-primary" />}
          titulo={`Métrica LLM-as-judge — rúbrica ${juez.tipo} (${juez.calificacion.puntaje}/${juez.calificacion.maximo})`}
        >
          <p className="text-xs text-muted-foreground mb-3">
            Evaluación independiente con la rúbrica de tu tipo de investigación (escala /100).
            Segunda mirada complementaria; no es tu calificación oficial.
          </p>
          <ul>
            {juez.calificacion.items.map((it, i) => (
              <li key={`mj-${i}`} className="py-2.5 border-b border-border/60 last:border-0">
                <div className="flex items-start gap-3">
                  <span className="shrink-0 text-xs font-semibold bg-muted rounded-xl px-2 py-1">
                    {it.numero}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px]">{it.descripcion}</p>
                    {it.razon && <p className="mt-1 text-xs text-muted-foreground">{it.razon}</p>}
                  </div>
                  <span className="shrink-0 text-sm font-semibold tabular-nums">
                    {it.puntaje ?? "—"}/{it.maximo}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Tarjeta>
      ) : null}

      {hayMetricas && (
      <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metrica
          nombre="LLM-as-Judge (G-Eval)"
          valor={`${m.llm_judge_score ?? 0} / ${m.llm_judge_max ?? 0}`}
          ayuda="Juez externo con rúbrica especializada"
        />
        <Metrica
          nombre="Gain Score (Hake)"
          valor={`${m.gain_score >= 0 ? "+" : ""}${Number(m.gain_score ?? 0).toFixed(4)}`}
          ayuda={m.gain_score_interpretacion}
        />
        <Metrica
          nombre="Similitud coseno (e5)"
          valor={Number(m.similitud_coseno ?? 0).toFixed(4)}
          ayuda={m.similitud_coseno_interpretacion}
        />
        <Metrica
          nombre="Context Precision"
          valor={Number(m.context_precision ?? 0).toFixed(4)}
          ayuda={m.context_precision_interpretacion}
        />
      </div>

      {m.iterative_consistency_has_iter && trayectoria.length > 0 && (
        <Tarjeta
          icono={<TrendingUp className="w-4 h-4 text-primary" />}
          titulo="Trayectoria de la rúbrica por iteración (red multiagente)"
        >
          <p className="text-xs text-muted-foreground mb-2">
            Nota de tu rúbrica en cada iteración de la red. El juez LLM (G-Eval) solo se evalúa
            antes y después (para el Gain Score), no en cada iteración.
          </p>
          <p className="text-sm tabular-nums">{trayectoria.join("  →  ")}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            La red conserva la <span className="font-medium text-foreground">mejor</span> versión: si una
            reescritura puntúa más bajo, se descarta y se mantiene la anterior. Por eso tu nota final puede
            ser mayor que el último valor de esta secuencia — no es un error: significa que tu texto ya era
            el mejor y las reescrituras no lo superaron.
          </p>
        </Tarjeta>
      )}

      {items.length > 0 && (
        <Tarjeta titulo="Evaluación detallada del Juez LLM (G-Eval)">
          <p className="text-xs text-muted-foreground mb-3">
            Juez externo independiente (rúbrica de tu tipo de investigación), complementario y solo
            antes/después. Tu calificación oficial por ítem, con lo que falta para el máximo, está en
            la pestaña <span className="font-medium text-foreground">Rúbrica</span>.
          </p>
          {Array.isArray(m.llm_judge_secciones) && m.llm_judge_secciones.length > 0 && (
            <p className="text-xs text-muted-foreground mb-3">
              Secciones de la rúbrica seleccionadas: {m.llm_judge_secciones.join(", ")}
            </p>
          )}
          <ul>
            {items.map((it: any, i: number) => (
              <li key={i} className="py-2.5 border-b border-border/60 last:border-0">
                <div className="flex items-start gap-3">
                  <span className="shrink-0 text-xs font-semibold bg-muted rounded-xl px-2 py-1">
                    {it.item_id ?? "?"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px]">{it.descripcion}</p>
                    {it.razon && (
                      <p className="mt-1 text-xs text-muted-foreground">{it.razon}</p>
                    )}
                  </div>
                  <span className="shrink-0 text-sm font-semibold tabular-nums">
                    {it.pts_obtenido}/{it.pts_max}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Tarjeta>
      )}
      </>
      )}
    </>
  );
}
