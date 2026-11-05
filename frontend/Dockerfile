# Node's October security release fixes CVE-2026-111497 in its vendored Brotli.
# Pin the patched official image so a runner's old floating-tag cache cannot win.
FROM node:24.22.1-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS build
ARG RELEASE_ID=development

WORKDIR /app
RUN node -e 'const [major,minor,patch]=process.versions.node.split(".").map(Number); if(major!==24 || minor<22 || (minor===22 && patch<1)) throw new Error("CVE-2026-111497: use patched Node 24.22.1 or newer in the 24.x line"); console.log(JSON.stringify({node:process.versions.node,brotli:process.versions.brotli}));'
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
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
