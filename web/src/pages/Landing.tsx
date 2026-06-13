import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Bot,
  BrainCircuit,
  FileSearch,
  GraduationCap,
  MessageSquareText,
  Scale,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";

const AGENTES = [
  { nombre: "Auditor", icono: FileSearch, color: "#FF9500" },
  { nombre: "Metodólogo", icono: BrainCircuit, color: "#5856D6" },
  { nombre: "Redactor", icono: MessageSquareText, color: "#34C759" },
  { nombre: "Debate", icono: Users, color: "#FF2D55" },
  { nombre: "Consenso", icono: Scale, color: "#007AFF" },
  { nombre: "Disenso", icono: Sparkles, color: "#AF52DE" },
];

const aparecer = {
  hidden: { opacity: 0, y: 24 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.12, duration: 0.55, ease: "easeOut" },
  }),
};

export default function Landing({ autenticado }: { autenticado: boolean }) {
  const destino = autenticado ? "/app" : "/auth";

  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="fixed top-0 inset-x-0 z-50">
        <div className="mx-auto max-w-6xl px-5 py-3">
          <div className="glass rounded-2xl px-5 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold">
              <GraduationCap className="w-5 h-5 text-primary" />
              MentorIA
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              {!autenticado && (
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/auth">Iniciar sesión</Link>
                </Button>
              )}
              <Button size="sm" className="rounded-full px-4" asChild>
                <Link to={destino}>
                  {autenticado ? "Ir al chat" : "Comenzar"}
                  <ArrowRight className="w-4 h-4 ml-1.5" />
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </header>

      <section className="relative pt-36 pb-20 px-5">
        <motion.div
          aria-hidden
          className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-[#007AFF]/15 blur-3xl"
          animate={{ x: [0, 40, 0], y: [0, 24, 0] }}
          transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          aria-hidden
          className="absolute top-40 -right-24 w-[28rem] h-[28rem] rounded-full bg-[#AF52DE]/15 blur-3xl"
          animate={{ x: [0, -36, 0], y: [0, 30, 0] }}
          transition={{ duration: 17, repeat: Infinity, ease: "easeInOut" }}
        />

        <div className="relative mx-auto max-w-6xl grid lg:grid-cols-2 gap-14 items-center">
          <div>
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 text-sm text-muted-foreground mb-6"
            >
              <Bot className="w-4 h-4 text-primary" />
              Red de 7 agentes orquestada con LangGraph
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.08 }}
              className="text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.08]"
            >
              Tu proyecto de tesis,
              <br />
              revisado por un <span className="text-gradient">panel de IA</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.18 }}
              className="mt-5 text-lg text-muted-foreground max-w-xl leading-relaxed"
            >
              Sube tu borrador y conversa con una red multiagente que audita con la
              rúbrica oficial, debate entre evaluadores y te propone el texto
              mejorado — fundamentado en 4 libros de metodología indexados.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.28 }}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              <Button size="lg" className="rounded-full px-7 text-base shadow-lg shadow-primary/25" asChild>
                <Link to={destino}>
                  Revisar mi tesis
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Link>
              </Button>
              <span className="text-sm text-muted-foreground">
                Rúbrica UPAO de 33 ítems incluida
              </span>
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, delay: 0.2 }}
            className="relative mx-auto w-[320px] h-[320px] sm:w-[400px] sm:h-[400px]"
          >
            <div className="absolute inset-0 rounded-full border border-dashed border-primary/25" />
            <div className="absolute inset-10 rounded-full border border-dashed border-primary/15" />

            <div className="absolute inset-0 grid place-items-center">
              <motion.div
                animate={{ scale: [1, 1.06, 1] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                className="glass rounded-3xl px-5 py-4 text-center"
              >
                <Bot className="w-8 h-8 text-primary mx-auto" />
                <div className="mt-1 text-sm font-semibold">Supervisor</div>
                <div className="text-[11px] text-muted-foreground">orquesta la red</div>
              </motion.div>
            </div>

            <motion.div
              className="absolute inset-0"
              animate={{ rotate: 360 }}
              transition={{ duration: 42, repeat: Infinity, ease: "linear" }}
            >
              {AGENTES.map((a, i) => {
                const ang = (i / AGENTES.length) * 2 * Math.PI;
                const x = 50 + 46 * Math.cos(ang);
                const y = 50 + 46 * Math.sin(ang);
                const Icono = a.icono;
                return (
                  <motion.div
                    key={a.nombre}
                    className="absolute -translate-x-1/2 -translate-y-1/2"
                    style={{ left: `${x}%`, top: `${y}%` }}
                    animate={{ rotate: -360 }}
                    transition={{ duration: 42, repeat: Infinity, ease: "linear" }}
                  >
                    <div className="glass rounded-2xl px-3 py-2 flex items-center gap-1.5 whitespace-nowrap">
                      <Icono className="w-4 h-4" style={{ color: a.color }} />
                      <span className="text-xs font-medium">{a.nombre}</span>
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          </motion.div>
        </div>
      </section>

      <section className="px-5 py-16">
        <div className="mx-auto max-w-6xl">
          <motion.h2
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-80px" }}
            variants={aparecer}
            custom={0}
            className="text-3xl font-semibold text-center tracking-tight"
          >
            Cómo funciona
          </motion.h2>

          <div className="mt-10 grid sm:grid-cols-3 gap-5">
            {[
              {
                paso: "1",
                titulo: "Sube tu borrador",
                texto:
                  "El sistema detecta el índice, descompone tu proyecto por secciones y lo indexa con embeddings locales.",
              },
              {
                paso: "2",
                titulo: "Pide la revisión en el chat",
                texto:
                  "«Revisa mis objetivos» o «evalúa todo el proyecto». El Supervisor decide qué agentes intervienen y tú ves cada paso en vivo.",
              },
              {
                paso: "3",
                titulo: "Recibe el plan de mejora",
                texto:
                  "Puntos débiles priorizados, síntesis del debate entre evaluadores y propuesta de texto mejorado para lo que más lo necesita.",
              },
            ].map((item, i) => (
              <motion.div
                key={item.paso}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, margin: "-60px" }}
                variants={aparecer}
                custom={i + 1}
                className="glass rounded-3xl p-6"
              >
                <div className="w-9 h-9 rounded-full bg-primary text-primary-foreground grid place-items-center font-semibold">
                  {item.paso}
                </div>
                <h3 className="mt-4 font-semibold text-lg">{item.titulo}</h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {item.texto}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 py-16">
        <div className="mx-auto max-w-6xl grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {[
            {
              icono: ShieldCheck,
              titulo: "Rúbrica oficial",
              texto: "Audita contra los 33 ítems de la ficha UPAO, o sube la rúbrica de tu jurado.",
            },
            {
              icono: BookOpen,
              titulo: "Memoria RAG",
              texto: "4 libros de metodología de investigación indexados respaldan cada observación.",
            },
            {
              icono: Users,
              titulo: "Debate multiagente",
              texto: "Un panel de 4 subagentes discute las observaciones y emite un veredicto de consenso.",
            },
            {
              icono: Sparkles,
              titulo: "Anti token-burn",
              texto: "RAG por secciones y revisión completa en fases: profundiza solo donde hay debilidades.",
            },
          ].map((f, i) => {
            const Icono = f.icono;
            return (
              <motion.div
                key={f.titulo}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, margin: "-60px" }}
                variants={aparecer}
                custom={i}
                className="glass rounded-3xl p-6 animate-float-slow"
                style={{ animationDelay: `${i * 0.6}s` }}
              >
                <Icono className="w-6 h-6 text-primary" />
                <h3 className="mt-3 font-semibold">{f.titulo}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{f.texto}</p>
              </motion.div>
            );
          })}
        </div>
      </section>

      <section className="px-5 py-20">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="mx-auto max-w-3xl glass rounded-3xl p-10 text-center"
        >
          <h2 className="text-3xl font-semibold tracking-tight">
            Tu jurado hará preguntas difíciles.
            <br />
            <span className="text-gradient">Llega con las respuestas.</span>
          </h2>
          <Button size="lg" className="mt-7 rounded-full px-8 text-base shadow-lg shadow-primary/25" asChild>
            <Link to={destino}>
              Crear cuenta gratis
              <ArrowRight className="w-4 h-4 ml-2" />
            </Link>
          </Button>
        </motion.div>
      </section>

      <footer className="px-5 py-8 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} MentorIA — Sistema multiagente de mentoría académica
      </footer>
    </div>
  );
}
