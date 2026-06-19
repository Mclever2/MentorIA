import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import { Award, ChartNoAxesColumn, GraduationCap } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AccionMensaje, AnalisisDetalle, Mensaje, RevisionCompleta } from "@/types";
import EstructuraCards from "./EstructuraCards";

interface MessageBubbleProps {
  mensaje: Mensaje;
  onVerAnalisis?: (detalle: AnalisisDetalle) => void;
  onVerRevision?: (revision: RevisionCompleta) => void;
  onAccion?: (mensajeId: string, flags: AccionMensaje["flags"]) => void;
}

export default function MessageBubble({ mensaje, onVerAnalisis, onVerRevision, onAccion }: MessageBubbleProps) {
  if (mensaje.tipo === "estructura" && mensaje.estructura) {
    return (
      <div className="w-full">
        <EstructuraCards estructura={mensaje.estructura} />
      </div>
    );
  }

  if (mensaje.rol === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end"
      >
        <div className="max-w-[78%] rounded-3xl rounded-br-lg bg-primary text-primary-foreground px-5 py-3 text-[15px] leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          {mensaje.contenido}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3"
    >
      <div className="w-8 h-8 rounded-full bg-card shadow-sm border border-border grid place-items-center shrink-0">
        <GraduationCap className="w-5 h-5 text-primary" />
      </div>
      <div className="max-w-[85%] glass rounded-3xl rounded-tl-lg px-5 py-4 text-[15px]">
        <div className="prose-informe">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{mensaje.contenido}</ReactMarkdown>
        </div>

        {mensaje.revision && onVerRevision && (
          <div className="mt-3 pt-3 border-t border-border/60">
            <Button
              variant="default"
              size="sm"
              onClick={() => onVerRevision(mensaje.revision!)}
              className="rounded-full text-xs h-8 gap-1.5"
            >
              <Award className="w-3.5 h-3.5" />
              Ver calificación completa — {mensaje.revision.calificacion.puntaje}/
              {mensaje.revision.calificacion.maximo} pts
            </Button>
          </div>
        )}

        {mensaje.detalles && mensaje.detalles.length > 0 && onVerAnalisis && (
          <div className="mt-3 pt-3 border-t border-border/60 flex flex-wrap gap-2">
            {mensaje.detalles.map((d, i) => (
              <Button
                key={i}
                variant="outline"
                size="sm"
                onClick={() => onVerAnalisis(d)}
                className="rounded-full text-xs h-8 gap-1.5 bg-card/60"
              >
                <ChartNoAxesColumn className="w-3.5 h-3.5 text-primary" />
                Ver análisis completo
                {mensaje.detalles!.length > 1 && ` — ${d.seccion}`}
              </Button>
            ))}
          </div>
        )}

        {mensaje.acciones && mensaje.acciones.length > 0 && onAccion && (
          <div className="mt-3 pt-3 border-t border-border/60 flex flex-wrap gap-2">
            {mensaje.acciones.map((a, i) => (
              <Button
                key={i}
                size="sm"
                variant={a.variante === "secundaria" ? "outline" : "default"}
                onClick={() => onAccion(mensaje.id, a.flags)}
                className="rounded-full text-xs h-8"
              >
                {a.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
