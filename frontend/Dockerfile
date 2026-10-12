# syntax=docker/dockerfile:1
# Builds the Angular app and serves it with nginx (non-root, port 8080).
# On AWS the build output is uploaded to S3/CloudFront instead (see docs/AWS_DEPLOYMENT.md);
# this image is used for the local production-like stack and other container hosts.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx ng build --configuration production

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
EXPOSE 8080
