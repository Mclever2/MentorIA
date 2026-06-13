import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import type { Session } from "@supabase/supabase-js";

import { supabase, supabaseHabilitado } from "@/lib/supabase";
import Landing from "@/pages/Landing";
import Auth from "@/pages/Auth";
import Chat from "@/pages/Chat";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [cargando, setCargando] = useState(supabaseHabilitado);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth
      .getSession()
      .then(({ data }) => setSession(data.session))
      .catch(() => setSession(null))
      .finally(() => setCargando(false));
    const { data: sub } = supabase.auth.onAuthStateChange((_evt, s) => {
      setSession(s);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  if (cargando) {
    return (
      <div className="min-h-screen grid place-items-center text-muted-foreground">
        Cargando…
      </div>
    );
  }

  const autenticado = !supabaseHabilitado || session !== null;

  return (
    <Routes>
      <Route path="/" element={<Landing autenticado={autenticado} />} />
      <Route
        path="/auth"
        element={autenticado ? <Navigate to="/app" replace /> : <Auth />}
      />
      <Route
        path="/app"
        element={autenticado ? <Chat session={session} /> : <Navigate to="/auth" replace />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
