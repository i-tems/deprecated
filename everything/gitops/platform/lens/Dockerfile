FROM python:3.12-slim

ARG GIT_SHA=dev
ENV LENS_GIT_SHA=${GIT_SHA} \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY dashboards ./dashboards

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
