# syntax=docker/dockerfile:1
# Build context: ui/. This image *is* the app-level nginx — it serves the built SPA and
# (see deploy/nginx/default.conf.template, mounted at runtime) proxies /api to the backend
# and /oauth2 to oauth2-proxy. ui/ is a plain Vite SPA (no server-side rendering), so there
# is no separate Node runtime container.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
