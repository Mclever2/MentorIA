import { useState } from "react";
import { Moon, Sun } from "lucide-react";

import { aplicarTema, temaActual, type Tema } from "@/lib/theme";
import { cn } from "@/lib/utils";

export default function ThemeToggle({ className }: { className?: string }) {
  const [tema, setTema] = useState<Tema>(temaActual());

  function alternar() {
    const nuevo: Tema = tema === "claro" ? "oscuro" : "claro";
    aplicarTema(nuevo);
    setTema(nuevo);
  }

  return (
    <button
      onClick={alternar}
      title={tema === "claro" ? "Modo nocturno" : "Modo claro"}
      className={cn(
        "w-9 h-9 rounded-full grid place-items-center transition-colors",
        "text-muted-foreground hover:text-foreground hover:bg-muted",
        className,
      )}
    >
      {tema === "claro" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
    </button>
  );
}
