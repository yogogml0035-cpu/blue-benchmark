# Production image for the Next.js admin console.
#
# Build from the frontend/ directory:
#   docker buildx build --platform linux/amd64 -t skill-eval-web:<tag> frontend/
#
# The browser only talks to the same-origin /api prefix; Next.js rewrites it
# to the FastAPI backend via the server-side BACKEND_URL env var.

FROM node:24-alpine AS deps
RUN npm install -g pnpm@11
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS build
RUN npm install -g pnpm@11
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24-alpine AS run
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
# standalone output is self-contained; static assets and public files must
# be copied separately or the pages 404 on their assets.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
# Non-root runtime user.
USER node
CMD ["node", "server.js"]
