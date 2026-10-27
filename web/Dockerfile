# Chào Bà family app (Next.js standalone output). Build from web/:
#   docker build -t chaoba-web --build-arg NEXT_PUBLIC_API_BASE=http://localhost:8000 web
#   docker run -p 3000:3000 -e CHAOBA_API_INTERNAL=http://host.docker.internal:8000 chaoba-web
# NEXT_PUBLIC_API_BASE = API address the *browser* uses (inlined at build time).
# CHAOBA_API_INTERNAL  = API address the *Next server* uses for server-side reads (runtime; defaults to the above).
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/manifest.webmanifest >/dev/null || exit 1
CMD ["node", "server.js"]
