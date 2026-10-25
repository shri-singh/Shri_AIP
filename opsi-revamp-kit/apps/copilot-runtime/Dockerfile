# Minimal, non-root image for the CopilotKit V2 runtime bridge.
# Pin the base image digest in your registry mirror: docker buildx imagetools inspect node:22-alpine
FROM node:22-alpine AS build
WORKDIR /app
ENV SCARF_ANALYTICS=false COPILOTKIT_TELEMETRY_DISABLED=true DO_NOT_TRACK=1
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production COPILOTKIT_TELEMETRY_DISABLED=true DO_NOT_TRACK=1
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
USER node
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q -O- http://127.0.0.1:4000/healthz || exit 1
CMD ["node", "dist/main.js"]
