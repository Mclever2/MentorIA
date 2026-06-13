import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { FileUp, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

interface UploadZoneProps {
  subiendo: boolean;
  etapa: string;
  onArchivo: (archivo: File) => void;
}

export default function UploadZone({ subiendo, etapa, onArchivo }: UploadZoneProps) {
  const [arrastrando, setArrastrando] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
    >
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onArchivo(f);
          e.target.value = "";
        }}
      />
      <button
        disabled={subiendo}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          const f = e.dataTransfer.files?.[0];
          if (f && f.type === "application/pdf") onArchivo(f);
        }}
        className={cn(
          "w-full glass rounded-3xl px-8 py-10 text-center transition-all",
          arrastrando && "ring-2 ring-primary scale-[1.01]",
          subiendo && "cursor-wait",
        )}
      >
        {subiendo ? (
          <>
            <Loader2 className="w-7 h-7 text-primary mx-auto animate-spin" />
            <p className="mt-3 font-medium">{etapa}</p>
            <div className="mt-3 mx-auto max-w-xs h-1.5 rounded-full bg-muted overflow-hidden">
              <div className="h-full w-full bg-gradient-to-r from-primary/30 via-primary to-primary/30 bg-[length:200%_100%] animate-shimmer rounded-full" />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Los embeddings se generan en el servidor — tu documento no se envía a terceros.
            </p>
          </>
        ) : (
          <>
            <FileUp className="w-7 h-7 text-primary mx-auto" />
            <p className="mt-3 font-medium">Arrastra tu proyecto de tesis (PDF)</p>
            <p className="mt-1 text-sm text-muted-foreground">
              o haz clic para seleccionarlo — detectaré su estructura automáticamente
            </p>
          </>
        )}
      </button>
    </motion.div>
  );
}
