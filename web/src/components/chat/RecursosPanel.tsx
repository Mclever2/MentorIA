import { useEffect, useRef, useState } from "react";
import {
  Building2,
  Check,
  ChevronDown,
  ClipboardList,
  Eye,
  Pencil,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import ProgresoBarra from "@/components/chat/ProgresoBarra";
import { cn } from "@/lib/utils";
import type { PerfilUniversidad, RubricaPersist } from "@/types";

interface Props {
  rubrica: RubricaPersist | null;
  perfil: PerfilUniversidad | null;
  hayProyecto: boolean;
  cargandoRubrica: boolean;
  cargandoPerfil: boolean;
  estadoRubrica: string;
  estadoPerfil: string;
  onSubirRubrica: (file: File) => void;
  onEliminarRubrica: () => void;
  onVerRubrica: () => void;
  onBuscarUniversidad: (universidad: string, nivel: string) => void;
  onSubirReglamento: (file: File, universidad: string, nivel: string) => void;
  onEliminarPerfil: () => void;
  onVerPerfil: () => void;
}

const NIVELES = ["pregrado", "maestría", "doctorado"];

function Dropdown({ valor, onCambio }: { valor: string; onCambio: (v: string) => void }) {
  const [abierto, setAbierto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!abierto) return;
    const cerrar = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", cerrar);
    return () => document.removeEventListener("mousedown", cerrar);
  }, [abierto]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        className="w-full flex items-center justify-between rounded-lg border border-input bg-card/70 px-2.5 py-1.5 text-[12px] outline-none focus:ring-1 focus:ring-ring"
      >
        <span className="capitalize">{valor}</span>
        <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", abierto && "rotate-180")} />
      </button>
      {abierto && (
        <ul className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-card shadow-lg overflow-hidden">
          {NIVELES.map((n) => (
            <li key={n}>
              <button
                type="button"
                onClick={() => {
                  onCambio(n);
                  setAbierto(false);
                }}
                className={cn(
                  "w-full text-left px-2.5 py-1.5 text-[12px] capitalize flex items-center justify-between hover:bg-muted",
                  n === valor && "text-primary font-medium",
                )}
              >
                {n}
                {n === valor && <Check className="w-3.5 h-3.5" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function RecursosPanel(props: Props) {
  const rubricaRef = useRef<HTMLInputElement>(null);
  const reglamentoRef = useRef<HTMLInputElement>(null);
  const [universidad, setUniversidad] = useState(props.perfil?.universidad ?? "");
  const [nivel, setNivel] = useState(props.perfil?.nivel ?? "pregrado");
  const [editando, setEditando] = useState(false);

  // Al encontrar/actualizar un perfil, salir del modo edición.
  useEffect(() => {
    if (props.perfil) {
      setEditando(false);
      setUniversidad(props.perfil.universidad);
      setNivel(props.perfil.nivel);
    }
  }, [props.perfil]);

  const modoBusqueda = !props.perfil || editando;

  return (
    <div className="px-4 pb-3 space-y-3">
      {/* ── Rúbrica ───────────────────────────────────────────── */}
      <div className="glass rounded-2xl p-3.5">
        <div className="flex items-center gap-2 text-sm font-medium mb-2">
          <ClipboardList className="w-4 h-4 text-primary" />
          Rúbrica de evaluación
        </div>

        <p className="text-[11.5px] text-muted-foreground mb-2 leading-snug">
          {props.rubrica
            ? `${props.rubrica.nombre} · ${props.rubrica.total_items} ítems`
            : "Usando la rúbrica UPAO por defecto."}
        </p>

        {props.cargandoRubrica ? (
          <ProgresoBarra texto={props.estadoRubrica || "Transformando y cargando…"} />
        ) : (
          <>
            <input
              ref={rubricaRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) props.onSubirRubrica(f);
                e.target.value = "";
              }}
            />
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                variant="outline"
                className="rounded-full h-7 text-[12px] gap-1"
                disabled={!props.hayProyecto}
                onClick={() => rubricaRef.current?.click()}
              >
                <Upload className="w-3 h-3" /> {props.rubrica ? "Cambiar" : "Subir"}
              </Button>
              {props.rubrica && (
                <>
                  <Button size="sm" variant="outline" className="rounded-full h-7 text-[12px] gap-1"
                    onClick={props.onVerRubrica}>
                    <Eye className="w-3 h-3" /> Ver
                  </Button>
                  <Button size="sm" variant="ghost" className="rounded-full h-7 text-[12px] gap-1 text-destructive"
                    onClick={props.onEliminarRubrica}>
                    <Trash2 className="w-3 h-3" /> Quitar
                  </Button>
                </>
              )}
            </div>
            {!props.hayProyecto && (
              <p className="mt-1.5 text-[10.5px] text-muted-foreground">
                Sube primero tu proyecto: la rúbrica se mapea a sus secciones al cargarla.
              </p>
            )}
          </>
        )}
      </div>

      {/* ── Universidad / Reglamento ──────────────────────────── */}
      <div className="glass rounded-2xl p-3.5 relative z-30">
        <div className="flex items-center gap-2 text-sm font-medium mb-2">
          <Building2 className="w-4 h-4 text-primary" />
          Universidad / Reglamento
        </div>

        {props.perfil ? (
          <p className="text-[11.5px] text-muted-foreground mb-2 leading-snug">
            {props.perfil.universidad} · {props.perfil.nivel}
            <br />
            <span className="opacity-70">{props.perfil.fuente}</span>
          </p>
        ) : (
          <p className="text-[11.5px] text-muted-foreground mb-2 leading-snug">
            Sin reglamento adicional: los agentes usan su criterio base.
          </p>
        )}

        {props.cargandoPerfil ? (
          <ProgresoBarra texto={props.estadoPerfil || "Buscando reglamentos…"} />
        ) : !modoBusqueda ? (
          // Ya hay perfil: ver / cambiar / quitar (sin recuadro de búsqueda)
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="outline" className="rounded-full h-7 text-[12px] gap-1"
              onClick={props.onVerPerfil}>
              <Eye className="w-3 h-3" /> Ver
            </Button>
            <Button size="sm" variant="outline" className="rounded-full h-7 text-[12px] gap-1"
              onClick={() => setEditando(true)}>
              <Pencil className="w-3 h-3" /> Cambiar
            </Button>
            <Button size="sm" variant="ghost" className="rounded-full h-7 text-[12px] gap-1 text-destructive"
              onClick={props.onEliminarPerfil}>
              <Trash2 className="w-3 h-3" /> Quitar
            </Button>
          </div>
        ) : (
          // Sin perfil o editando: buscar / subir
          <>
            <input
              value={universidad}
              onChange={(e) => setUniversidad(e.target.value)}
              placeholder="Nombre de la universidad"
              className="w-full mb-1.5 rounded-lg border border-input bg-card/70 px-2.5 py-1.5 text-[12px] outline-none focus:ring-1 focus:ring-ring"
            />
            <div className="mb-2">
              <Dropdown valor={nivel} onCambio={setNivel} />
            </div>
            <input
              ref={reglamentoRef}
              type="file"
              accept="application/pdf,.docx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) props.onSubirReglamento(f, universidad.trim(), nivel);
                e.target.value = "";
              }}
            />
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" className="rounded-full h-7 text-[12px] gap-1"
                disabled={!universidad.trim()}
                onClick={() => props.onBuscarUniversidad(universidad.trim(), nivel)}>
                <Search className="w-3 h-3" /> Buscar
              </Button>
              <Button size="sm" variant="outline" className="rounded-full h-7 text-[12px] gap-1"
                disabled={!universidad.trim()}
                onClick={() => reglamentoRef.current?.click()}>
                <Upload className="w-3 h-3" /> Subir
              </Button>
              {props.perfil && editando && (
                <Button size="sm" variant="ghost" className="rounded-full h-7 text-[12px]"
                  onClick={() => setEditando(false)}>
                  Cancelar
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
