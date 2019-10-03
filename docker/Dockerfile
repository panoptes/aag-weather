FROM python:3.7-slim as base
LABEL MAINTAINER Developers for PANOPTES project<https://github.com/panoptes/POCS>

ENV LANG=C.UTF-8

FROM base as builder
RUN mkdir /install
WORKDIR /install

COPY requirements.txt /requirements.txt

RUN  apt-get update && \
    apt-get install -y --no-install-recommends \
        pkg-config gcc build-essential libfreetype6-dev && \
    pip install --install-option="--prefix=/install" -r /requirements.txt && \
    # Cleanup apt.
    apt-get autoremove --purge -y gcc build-essential libfreetype6-dev pkg-config && \
    apt-get autoremove --purge -y && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*

FROM base

ENV PYTHONPATH=/install:${PYTHONPATH}

COPY --from=builder /install /usr/local
COPY . /app
RUN cd /app && \
    pip install --install-option="--prefix=/install" .

WORKDIR /app

CMD ["python", "/app/scripts/read-aag.py", "--config-file", "/app/config.yaml"]
