import { useEffect, useRef } from "react";
import { motion, useMotionValue, useSpring } from "framer-motion";

import { cn } from "@/lib/utils";

const GLOW_SIZE = 640;

export default function FondoLiquido({ intenso = false }: { intenso?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const x = useMotionValue(-GLOW_SIZE);
  const y = useMotionValue(-GLOW_SIZE);
  const sx = useSpring(x, { damping: 25, stiffness: 150, mass: 0.5 });
  const sy = useSpring(y, { damping: 25, stiffness: 150, mass: 0.5 });

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return;
      x.set(e.clientX - rect.left - GLOW_SIZE / 2);
      y.set(e.clientY - rect.top - GLOW_SIZE / 2);
    }
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [x, y]);

  return (
    <div ref={ref} aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div
        className={cn(
          "absolute -top-32 left-[18%] h-96 w-96 rounded-full bg-primary/25 blur-[120px] animate-orb-pulse",
          intenso && "brightness-125",
        )}
      />
      <div
        className={cn(
          "absolute -bottom-28 right-[8%] h-[22rem] w-[22rem] rounded-full bg-[#AF52DE]/20 blur-[120px] animate-orb-pulse [animation-delay:2.2s]",
          intenso && "brightness-125",
        )}
      />
      <div
        className={cn(
          "absolute top-1/3 right-[28%] h-72 w-72 rounded-full bg-[#5856D6]/20 blur-[110px] animate-orb-pulse [animation-delay:4s]",
          intenso && "brightness-125",
        )}
      />
      <motion.div
        className="absolute rounded-full blur-[130px] opacity-[0.05] dark:opacity-[0.09]"
        style={{
          x: sx,
          y: sy,
          width: GLOW_SIZE,
          height: GLOW_SIZE,
          background:
            "radial-gradient(circle, rgba(0,122,255,0.5), rgba(88,86,214,0.25) 45%, transparent 70%)",
        }}
      />
    </div>
  );
}
