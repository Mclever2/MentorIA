import { motion } from "framer-motion";
import { ArrowLeft, ClipboardList } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RubricaPersist } from "@/types";

export default function RubricaTabla({
  rubrica,
  onCerrar,
}: {
  rubrica: RubricaPersist;
  onCerrar: () => void;
}) {
  // Mapa inverso item → secciones del proyecto donde aplica.
  const seccionesPorItem = new Map<number, string[]>();
  for (const [seccion, nums] of Object.entries(rubrica.mapa_secciones ?? {})) {
    for (const n of nums) {
      const arr = seccionesPorItem.get(n) ?? [];
      arr.push(seccion);
      seccionesPorItem.set(n, arr);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="absolute inset-0 z-30 bg-background flex flex-col"
    >
      <div className="border-b border-border bg-card/60 backdrop-blur-xl">
        <div className="mx-auto max-w-4xl px-5 py-4 flex items-center gap-3">
          <Button variant="ghost" size="icon" className="rounded-full" onClick={onCerrar}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="min-w-0">
            <h1 className="font-semibold text-lg truncate flex items-center gap-2">
              <ClipboardList className="w-5 h-5 text-primary" />
              {rubrica.nombre}
            </h1>
            <p className="text-xs text-muted-foreground">
              {rubrica.total_items} ítems · puntaje máximo {rubrica.puntaje_maximo} · esta rúbrica
              reemplaza a la UPAO por defecto
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-5 py-6">
          <ul className="glass rounded-3xl p-2">
            {rubrica.items.map((it) => {
              const secs = seccionesPorItem.get(it.numero) ?? [];
              return (
                <li key={it.numero} className="py-2.5 px-3 border-b border-border/60 last:border-0">
                  <div className="flex items-start gap-3">
                    <span className="shrink-0 w-8 h-8 rounded-xl bg-muted grid place-items-center text-xs font-semibold">
                      {String(it.numero).padStart(2, "0")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] leading-snug">{it.descripcion}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {secs.length > 0 ? (
                          <>Se evalúa en: {secs.join(" · ")}</>
                        ) : (
                          <span className="italic">No mapeado a ninguna sección del proyecto</span>
                        )}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </motion.div>
  );
}
