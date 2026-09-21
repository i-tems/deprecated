FROM registry.lab.i-tems.com/hive-capability-framework:main

RUN pip install --no-cache-dir google-api-python-client google-auth-oauthlib "gspread>=6,<7" watchfiles

COPY main.py .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
