FROM python:3.12-slim

RUN pip install --no-cache-dir kubernetes==31.0.0 httpx==0.27.2

WORKDIR /app
COPY app ./app

USER 65532
CMD ["python", "-m", "app.main"]
