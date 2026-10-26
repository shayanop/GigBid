# Next.js web app. Rewrites are resolved at build time, so API_URL is a build argument.
FROM node:24.22.1-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN npm ci
COPY apps/web ./
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM node:24.22.1-alpine
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web ./
EXPOSE 3000
CMD ["npx", "next", "start", "--port", "3000"]
