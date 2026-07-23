FROM node:20-alpine AS tools

WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package*.json ./
RUN npm ci
COPY --chown=node:node . .

FROM tools AS build
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY --chown=101:101 --chmod=644 nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=4s --retries=12 --start-period=5s \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
