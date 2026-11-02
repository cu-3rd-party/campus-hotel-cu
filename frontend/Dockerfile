FROM node:24-alpine AS build
ARG RELEASE_ID=development

WORKDIR /app
COPY package*.json ./
# npm ci вместо npm install: ставит строго по package-lock.json — быстрее
# и воспроизводимо. Кэш npm — в BuildKit-кэше, чтобы не качать по сети заново.
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY . .
RUN npm run build
RUN node -e 'require("node:fs").writeFileSync("dist/version.json", JSON.stringify({commit: process.env.RELEASE_ID || "development"}))'

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
