// Barra de progreso indeterminada (transformación/carga de rúbrica o reglamento).
export default function ProgresoBarra({ texto }: { texto?: string }) {
  return (
    <div className="mt-2">
      {texto && <p className="text-[10.5px] text-muted-foreground mb-1 truncate">{texto}</p>}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-1/3 rounded-full bg-primary animate-progreso-indeterminado" />
      </div>
    </div>
  );
}
