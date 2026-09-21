FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates xvfb xauth \
        libnss3 libatk-bridge2.0-0 libgtk-3-0 libasound2 libxss1 \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

RUN touch /root/.Xauthority

COPY requirements.txt /root/requirements.txt
RUN pip3 install --no-cache-dir -r /root/requirements.txt

COPY src /app
RUN mkdir -p /app/output
WORKDIR /app

EXPOSE 3200
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3200"]
