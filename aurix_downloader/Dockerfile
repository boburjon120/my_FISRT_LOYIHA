# AURIX Downloader — production image
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tashkent

# FFmpeg converts audio; ca-certificates/tzdata for HTTPS and correct time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user. Named volumes inherit this ownership.
RUN useradd --create-home --uid 10001 aurix \
    && mkdir -p /app/data /app/downloads /app/logs \
    && chown -R aurix:aurix /app
USER aurix

VOLUME ["/app/data", "/app/downloads", "/app/logs"]

HEALTHCHECK --interval=2m --timeout=10s --start-period=2m --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "bot.py"]
