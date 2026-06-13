# ── Etapa 1: build de Vite ────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
# Las VITE_* se inyectan en build-time (quedan embebidas en el bundle estático)
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN npm run build

# ── Etapa 2: nginx sirviendo estáticos (~25 MB, arranque <1s) ────────────────
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Cloud Run inyecta PORT; la imagen oficial de nginx expande templates con envsubst
ENV PORT=8080
EXPOSE 8080
