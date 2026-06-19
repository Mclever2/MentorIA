import type { DocumentoInfo, EventoRun } from "@/lib/api";

export interface ItemRubrica {
  item_numero: number | string;
  criterio?: string;
  puntaje?: number;
  puntaje_actual?: number;
  maximo?: number;                 // máximo del ítem (juez por tipo, escala ponderada)
  observacion?: string;
  descripcion?: string;
}

export interface SesionDebate {
  veredicto: {
    veredicto_general?: string;
    justificacion?: string;
    items_confirmados?: number[];
    items_descartados?: number[];
    items_matizados?: number[];
  };
  panel: { subagente: string; contenido: string }[];
}

export interface AnalisisDetalle {
  run_id?: string;
  seccion: string;
  puntaje?: number | null;
  puntaje_max?: number | null;
  puntaje_inicial?: number | null;
  escala_max?: number;
  iteraciones?: number;
  max_iteraciones?: number;
  texto_mejorado?: string;
  feedback_auditor?: string;
  observaciones_metodologicas?: string;
  sugerencias_redactor?: string;
  errores_rubrica?: ItemRubrica[];
  evaluacion_inicial?: ItemRubrica[];
  evaluacion_final?: ItemRubrica[];
  consenso?: string;
  disenso?: string;
  debate?: { sesiones: SesionDebate[] };
  contexto_pdf?: string;
  contexto_cruzado?: string;
  contexto_teorico?: string;
  metricas?: Record<string, unknown>;
  metricas_juez?: MetricaJuez | null;   // rúbrica del tipo (LLM-as-judge, /100)
}

export interface AccionMensaje {
  label: string;
  variante?: "primaria" | "secundaria";
  flags: { confirmar_reevaluacion?: boolean; decision_mejoras?: "aplicar" | "mantener" } | null;
}

// Calificación por ítem de la revisión completa.
export interface RubricaItemEval {
  numero: number | string;
  descripcion: string;
  secciones?: string[];
  puntaje: number | null;          // null = no aplica por tipo
  maximo: number;
  estado: "ok" | "bajo" | "na" | "ausente";
  razon?: string;
}

export interface RevisionCompleta {
  calificacion: { puntaje: number; maximo: number; items: RubricaItemEval[] };
  fortalezas?: string[];
  debilidades?: string[];
  trazabilidad?: { coherente: boolean; observaciones: string };
}

// Métrica complementaria: rúbrica del tipo evaluada por LLM-as-judge (escala /100).
export interface MetricaJuez {
  tipo: string;
  fuente?: string;
  calificacion: { puntaje: number; maximo: number; items: RubricaItemEval[] };
}

export interface Mensaje {
  id: string;
  rol: "user" | "assistant";
  contenido: string;
  tipo?: "texto" | "estructura";
  estructura?: Pick<DocumentoInfo, "nombre" | "stats" | "estructura_toc">;
  detalles?: AnalisisDetalle[];
  revision?: RevisionCompleta;
  acciones?: AccionMensaje[];
}

export interface Conversacion {
  id: string;
  titulo: string;
  creada_en: string;
}

// Rúbrica subida por el estudiante (snapshot por sesión + default del usuario).
export interface RubricaItemDef {
  numero: number;
  descripcion: string;
  seccion?: string;
}

export interface RubricaPersist {
  nombre: string;
  items: RubricaItemDef[];
  mapa_secciones?: Record<string, number[]>;
  secciones?: Record<string, number[]>;
  escala?: Record<string, string>;
  items_ausentes?: { numero: number; descripcion: string }[];
  mapa_toc_firma?: string;
  total_items: number;
  puntaje_maximo: number;
}

// Perfil institucional destilado de los reglamentos de la universidad.
export interface PerfilUniversidad {
  universidad: string;
  programa: string;
  nivel: string;
  contexto_institucional: string;
  enfasis: string;
  fuente: string;
  advertencia?: string;
}

export interface PasoProgreso {
  id: number;
  texto: string;
  estado: "activo" | "completado";
}

export type { DocumentoInfo, EventoRun };
