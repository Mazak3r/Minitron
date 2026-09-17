# MINITRON — Single image, multiple services (core / radius / selenium)
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# ============ System packages ============
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    iputils-ping telnet openssh-client \
    && rm -rf /var/lib/apt/lists/*

# ============ Google Chrome (for Selenium) ============
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*


# ============ Python dependencies ============
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt



ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["core"]
