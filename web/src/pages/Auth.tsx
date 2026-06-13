import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Eye, EyeOff, GraduationCap, Loader2 } from "lucide-react";

import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { supabase } from "@/lib/supabase";

export default function Auth() {
  const navigate = useNavigate();
  const [modo, setModo] = useState<"login" | "registro">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verPassword, setVerPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setError(null);
    setAviso(null);
    setCargando(true);
    try {
      if (modo === "registro") {
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        if (data.session) {
          navigate("/app");
        } else {
          setAviso("Revisa tu correo para confirmar la cuenta y luego inicia sesión.");
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        navigate("/app");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Error de autenticación");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-5 relative overflow-hidden">
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle />
      </div>
      <motion.div
        aria-hidden
        className="absolute -top-32 -right-32 w-[30rem] h-[30rem] rounded-full bg-[#007AFF]/12 blur-3xl"
        animate={{ y: [0, 28, 0] }}
        transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
      />

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="relative w-full max-w-md"
      >
        <Link to="/" className="flex items-center justify-center gap-2 font-semibold mb-6">
          <GraduationCap className="w-6 h-6 text-primary" />
          MentorIA
        </Link>

        <div className="glass rounded-3xl p-8">
          <div className="bg-muted rounded-xl p-1 grid grid-cols-2 text-sm font-medium">
            {(["login", "registro"] as const).map((m) => (
              <button
                key={m}
                onClick={() => { setModo(m); setError(null); setAviso(null); }}
                className={`py-1.5 rounded-lg transition-all ${
                  modo === m ? "bg-card shadow-sm" : "text-muted-foreground"
                }`}
              >
                {m === "login" ? "Iniciar sesión" : "Crear cuenta"}
              </button>
            ))}
          </div>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div>
              <label className="text-sm font-medium">Correo</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@correo.com"
                className="mt-1.5 w-full rounded-xl border border-input bg-card px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Contraseña</label>
              <div className="relative mt-1.5">
                <input
                  type={verPassword ? "text" : "password"}
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Mínimo 6 caracteres"
                  className="w-full rounded-xl border border-input bg-card pl-3.5 pr-11 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <button
                  type="button"
                  onClick={() => setVerPassword((v) => !v)}
                  title={verPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                  aria-label={verPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 w-8 h-8 grid place-items-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                >
                  {verPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <p className="text-sm text-destructive bg-destructive/10 rounded-xl px-3.5 py-2.5">{error}</p>
            )}
            {aviso && (
              <p className="text-sm text-accent-foreground bg-accent rounded-xl px-3.5 py-2.5">{aviso}</p>
            )}

            <Button type="submit" disabled={cargando} className="w-full rounded-xl h-11 text-base">
              {cargando && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {modo === "login" ? "Entrar" : "Registrarme"}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs text-muted-foreground">
          Tus asesorías se guardan en tu cuenta y solo tú puedes verlas.
        </p>
      </motion.div>
    </div>
  );
}
