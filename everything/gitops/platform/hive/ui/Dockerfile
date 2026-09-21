# Multi-stage: vite build → nginx serve. 빌드 컨텍스트는 이 폴더 자체(self-contained).
FROM node:22-alpine AS build
ARG VITE_APP_NAME=Hive
ARG VITE_APP_LOGIN_SUBTITLE="Google 계정으로 로그인하세요"
ARG VITE_APP_TITLE_SUFFIX=Hive
ENV VITE_APP_NAME=${VITE_APP_NAME}
ENV VITE_APP_LOGIN_SUBTITLE=${VITE_APP_LOGIN_SUBTITLE}
ENV VITE_APP_TITLE_SUFFIX=${VITE_APP_TITLE_SUFFIX}
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf.template
COPY docker-entrypoint.d/ /docker-entrypoint.d/
EXPOSE 80

# rebuild trigger 1779082374
