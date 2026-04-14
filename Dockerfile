FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/app/output

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/GeiserX/Wayback-Archive.git /app

RUN pip install --no-cache-dir -r config/requirements.txt \
 && pip install --no-cache-dir .

RUN mkdir -p /app/output
VOLUME ["/app/output"]

ENTRYPOINT ["python3", "-m", "wayback_archive.cli"]
