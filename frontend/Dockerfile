# syntax=docker/dockerfile:1

# ---- build: instala dependências fixadas (npm ci) e gera os estáticos
FROM node:20.19-alpine AS build
# /app/frontend + /app/docs: o manual (docs/manual.md e os prints) vem do contexto "docs".
WORKDIR /app/frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=docs manual.md /app/docs/manual.md
COPY --from=docs img/manual /app/docs/img/manual
COPY . .
ARG VITE_DEMO_MODE=true
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE
RUN npm run build

# ---- runtime: nginx servindo o SPA e fazendo proxy da API (mesma origem, sem CORS)
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1/healthz || exit 1
