FROM registry.lab.i-tems.com/hive-capability-framework:main

RUN pip install --no-cache-dir "kubernetes>=35,<36" httpx websockets wsproto PyJWT

COPY main.py .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "30", "--ws-ping-timeout", "30"]
