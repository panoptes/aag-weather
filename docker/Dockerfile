FROM python:3.7-slim as base
LABEL MAINTAINER Developers for PANOPTES project<https://projectpanoptes.org>

ENV LANG=C.UTF-8

COPY . /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        pkg-config git gcc build-essential libfreetype6-dev && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    # Cleanup apt.
    apt-get autoremove --purge -y gcc build-essential pkg-config git && \
    apt-get autoremove --purge -y && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*

RUN cd /app && \
    pip install --no-cache-dir .

WORKDIR /app

CMD ["python", "/app/scripts/read-aag.py", "--config-file", "/app/config.yaml"]
