import { cn } from "@/lib/utils";

/**
 * Fondo de orbs degradados (estética iOS). ESTÁTICO a propósito: animar elementos
 * con blur de ~120px obliga a la GPU a recalcular el desenfoque en cada frame, lo
 * que traba el scroll de toda la app. Pintados una vez, el compositor los cachea.
 */
export default function FondoLiquido({ intenso = false }: { intenso?: boolean }) {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div
        className={cn(
          "absolute -top-32 left-[18%] h-96 w-96 rounded-full bg-primary/25 blur-[120px]",
          intenso && "brightness-125",
        )}
      />
      <div
        className={cn(
          "absolute -bottom-28 right-[8%] h-[22rem] w-[22rem] rounded-full bg-[#AF52DE]/20 blur-[120px]",
          intenso && "brightness-125",
        )}
      />
      <div
        className={cn(
          "absolute top-1/3 right-[28%] h-72 w-72 rounded-full bg-[#5856D6]/20 blur-[110px]",
          intenso && "brightness-125",
        )}
      />
    </div>
  );
}
