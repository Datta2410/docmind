FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
# npm install (not `npm ci`): the lockfile is generated on the host platform and
# omits linux-only optional native deps (@emnapi/*), which `npm ci` rejects.
# Phase 2: generate a complete cross-platform lock and restore `npm ci`.
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
