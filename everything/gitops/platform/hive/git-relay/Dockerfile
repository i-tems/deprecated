# stdlib 전용 — 의존성 없음. 작은 베이스로 빠른 빌드·작은 attack surface.
FROM python:3.12-alpine
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
WORKDIR /app
COPY app/ /app/
USER 1000
EXPOSE 8000
CMD ["python", "-u", "main.py"]
