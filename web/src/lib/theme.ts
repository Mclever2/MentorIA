export type Tema = "claro" | "oscuro";

const KEY = "mentoria-tema";

export function temaActual(): Tema {
  const guardado = localStorage.getItem(KEY);
  if (guardado === "claro" || guardado === "oscuro") return guardado;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
}

export function aplicarTema(tema: Tema) {
  document.documentElement.classList.toggle("dark", tema === "oscuro");
  localStorage.setItem(KEY, tema);
}

export function inicializarTema() {
  aplicarTema(temaActual());
}
