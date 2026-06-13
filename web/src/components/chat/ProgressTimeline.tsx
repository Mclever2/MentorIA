import { motion } from "framer-motion";
import { Bot, Check, Loader2 } from "lucide-react";

import type { PasoProgreso } from "@/types";

export default function ProgressTimeline({ pasos }: { pasos: PasoProgreso[] }) {
  if (pasos.length === 0) {
    return (
      <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin text-primary" />
        Conectando con la red de agentes…
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-sm font-medium mb-2">
        <Bot className="w-4 h-4 text-primary" />
        Red multiagente trabajando
      </div>
      {pasos.map((p) => (
        <motion.div
          key={p.id}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.25 }}
          className="flex items-start gap-2.5 text-[13px]"
        >
          {p.estado === "completado" ? (
            <span className="mt-0.5 w-4 h-4 rounded-full bg-[#34C759]/15 grid place-items-center shrink-0">
              <Check className="w-3 h-3 text-[#34C759]" />
            </span>
          ) : (
            <Loader2 className="mt-0.5 w-4 h-4 animate-spin text-primary shrink-0" />
          )}
          <span
            className={
              p.estado === "completado" ? "text-muted-foreground" : "text-foreground font-medium"
            }
          >
            {p.texto}
          </span>
        </motion.div>
      ))}
    </div>
  );
}
