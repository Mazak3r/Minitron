# MINITRON Cloud — Laravel UI + Python backend + Streamlit tools
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System tools + sury.org PHP repo for PHP 8.4
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget iputils-ping telnet openssh-client procps \
        ca-certificates gnupg unzip git lsb-release apt-transport-https \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://packages.sury.org/php/apt.gpg | gpg --dearmor -o /etc/apt/keyrings/sury-php.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/sury-php.gpg] https://packages.sury.org/php/ $(lsb_release -sc) main" \
         > /etc/apt/sources.list.d/sury-php.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        php8.4-cli php8.4-mbstring php8.4-xml php8.4-curl \
        php8.4-sqlite3 php8.4-zip php8.4-bcmath \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --set php /usr/bin/php8.4

# Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# User + directories (Force UID 1001 so it matches EC2 host)
RUN useradd -u 1001 -m -s /bin/bash mazakar \
    && mkdir -p /app /shared /var/log/minitron /tmp/minitron /app/config \
    && ln -sfn /app /home/mazakar/minitron_deploy \
    && chown -R 1001:1001 /app /shared /var/log/minitron /home/mazakar

WORKDIR /app

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy app files and set correct ownership immediately
COPY --chown=1001:1001 . /app/
RUN chmod +x /app/docker-entrypoint.sh

# Laravel: Nuke Pail and fix permissions BEFORE dropping to user 1001
USER root
RUN cd /app/laravel \
    && rm -rf bootstrap/cache/* \
    && sed -i '/laravel\/pail/d' composer.json \
    && sed -i '/laravel\/pail/d' vendor/composer/installed.json \
    && sed -i '/Pail/d' vendor/composer/installed.php \
    && mkdir -p storage/logs storage/framework/cache/data storage/framework/sessions storage/framework/views bootstrap/cache \
    && chown -R 1001:1001 storage bootstrap/cache \
    && chmod -R 777 storage bootstrap/cache

# Switch to the app user for the rest
USER 1001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["core"]
