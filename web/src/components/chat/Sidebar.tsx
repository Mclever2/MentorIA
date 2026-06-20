import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  GraduationCap,
  History,
  LogOut,
  MessageSquare,
  PlusIcon,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";

import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { obtenerBiblioteca } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Conversacion } from "@/types";

interface SidebarProps {
  email: string | null;
  conversaciones: Conversacion[];
  conversacionActiva: string | null;
  onNueva: () => void;
  onSeleccionar: (id: string) => void;
  onEliminar: (id: string) => void;
  onLogout: () => void;
  recursosSlot?: React.ReactNode;
  /** Estado del cajón en móvil. En ≥md el sidebar es columna fija y esto se ignora. */
  abierto?: boolean;
  onCerrar?: () => void;
}

type Tab = "historial" | "recursos";

export default function Sidebar({
  email,
  conversaciones,
  conversacionActiva,
  onNueva,
  onSeleccionar,
  onEliminar,
  onLogout,
  recursosSlot,
  abierto = false,
  onCerrar,
}: SidebarProps) {
  const [libros, setLibros] = useState<{ nombre: string; fragmentos: number }[]>([]);
  const [librosError, setLibrosError] = useState(false);
  const [tab, setTab] = useState<Tab>("historial");

  useEffect(() => {
    obtenerBiblioteca()
      .then((b) => setLibros(b.libros))
      .catch(() => setLibrosError(true));
  }, []);

  return (
    <aside
      className={cn(
        "w-72 shrink-0 h-screen flex flex-col bg-white/55 dark:bg-zinc-900/50 backdrop-blur-xl border-r border-border",
        // En móvil: cajón deslizante. En ≥md: columna fija de siempre (sin cambios).
        "max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:shadow-2xl max-md:transition-transform max-md:duration-300",
        abierto ? "max-md:translate-x-0" : "max-md:-translate-x-full",
      )}
    >
      <div className="flex items-center justify-between px-5 pt-5 pb-3">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <GraduationCap className="w-5 h-5 text-primary" />
          MentorIA
        </Link>
        <button
          onClick={onCerrar}
          className="md:hidden p-1.5 -mr-1.5 rounded-lg hover:bg-muted text-muted-foreground"
          aria-label="Cerrar menú"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="px-4">
        <Button
          onClick={() => {
            onNueva();
            onCerrar?.();
          }}
          variant="outline"
          className="w-full rounded-2xl justify-start gap-2 bg-card/70"
        >
          <PlusIcon className="w-4 h-4" />
          Nueva asesoría
        </Button>
      </div>

      {/* Pestañas: Historial / Recursos — cada una con su propio scroll */}
      <div className="px-4 mt-3">
        <div className="bg-muted rounded-xl p-1 grid grid-cols-2 text-[12.5px] font-medium">
          <button
            onClick={() => setTab("historial")}
            className={cn(
              "py-1.5 rounded-lg transition-all flex items-center justify-center gap-1.5",
              tab === "historial"
                ? "bg-card shadow-sm text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <History className="w-3.5 h-3.5" /> Historial
          </button>
          <button
            onClick={() => setTab("recursos")}
            className={cn(
              "py-1.5 rounded-lg transition-all flex items-center justify-center gap-1.5",
              tab === "recursos"
                ? "bg-card shadow-sm text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" /> Recursos
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto mt-3 min-h-0">
        {tab === "historial" ? (
          <div className="px-4">
            {conversaciones.length === 0 && (
              <p className="text-[13px] text-muted-foreground px-1">
                Tus asesorías aparecerán aquí.
              </p>
            )}
            <ul className="space-y-0.5">
              {conversaciones.map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    onClick={() => {
                      onSeleccionar(c.id);
                      onCerrar?.();
                    }}
                    className={cn(
                      "w-full text-left rounded-xl px-3 py-2 text-[13px] flex items-center gap-2 transition-colors",
                      c.id === conversacionActiva
                        ? "bg-accent text-accent-foreground font-medium"
                        : "hover:bg-muted text-foreground/80",
                    )}
                  >
                    <MessageSquare className="w-3.5 h-3.5 shrink-0" />
                    <span className="truncate pr-5">{c.titulo}</span>
                  </button>
                  <button
                    onClick={() => onEliminar(c.id)}
                    title="Eliminar asesoría"
                    className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <>
            {recursosSlot}

            <div className="px-4 pb-3">
              <div className="glass rounded-2xl p-3.5">
                <div className="flex items-center gap-2 text-sm font-medium mb-2">
                  <BookOpen className="w-4 h-4 text-primary" />
                  Memoria de los agentes
                </div>
                {librosError ? (
                  <p className="text-xs text-muted-foreground">
                    Biblioteca no disponible (backend despertando…)
                  </p>
                ) : libros.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Cargando biblioteca…</p>
                ) : (
                  <ul className="space-y-1.5">
                    {libros.map((l) => (
                      <li key={l.nombre} className="text-[11.5px] leading-snug">
                        <span className="line-clamp-2 text-foreground/80">{l.nombre}</span>
                        <span className="text-muted-foreground">
                          {l.fragmentos.toLocaleString("es")} fragmentos
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[10.5px] text-muted-foreground">
                  Los agentes fundamentan sus observaciones únicamente en estos libros (RAG).
                </p>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="px-4 pb-4 flex items-center justify-between gap-2 border-t border-border pt-3">
        <span className="text-xs text-muted-foreground truncate">
          {email ?? "Modo invitado"}
        </span>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          {email && (
            <Button variant="ghost" size="icon" title="Cerrar sesión" onClick={onLogout}>
              <LogOut className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    </aside>
  );
}
