import { motion } from "framer-motion";
import { ArrowLeft, Building2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PerfilUniversidad } from "@/types";

export default function PerfilModal({
  perfil,
  onCerrar,
}: {
  perfil: PerfilUniversidad;
  onCerrar: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="absolute inset-0 z-30 bg-background flex flex-col"
    >
      <div className="border-b border-border bg-card/60 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl px-5 py-4 flex items-center gap-3">
          <Button variant="ghost" size="icon" className="rounded-full" onClick={onCerrar}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="min-w-0">
            <h1 className="font-semibold text-lg truncate flex items-center gap-2">
              <Building2 className="w-5 h-5 text-primary" />
              {perfil.universidad}
            </h1>
            <p className="text-xs text-muted-foreground">
              {perfil.programa} · {perfil.nivel} · fuente: {perfil.fuente}
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-5 py-6 space-y-5">
          <section className="glass rounded-3xl p-5">
            <h2 className="font-semibold mb-2">Contexto institucional</h2>
            <p className="text-[14px] leading-relaxed whitespace-pre-wrap">
              {perfil.contexto_institucional || "—"}
            </p>
          </section>
          <section className="glass rounded-3xl p-5">
            <h2 className="font-semibold mb-2">Énfasis para los agentes</h2>
            <p className="text-[14px] leading-relaxed whitespace-pre-wrap">
              {perfil.enfasis || "—"}
            </p>
          </section>
          <p className="text-[11px] text-muted-foreground text-center">
            Los agentes adaptan su criterio y estilo a estos lineamientos en este chat.
          </p>
        </div>
      </div>
    </motion.div>
  );
}
