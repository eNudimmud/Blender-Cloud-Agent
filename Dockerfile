FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend ./frontend
RUN npm run build

FROM python:3.12-slim-bookworm AS base
WORKDIR /srv/app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_ROOT=/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 agent && mkdir /data && chown agent:agent /data
COPY app ./app

FROM base AS api
COPY --from=frontend /build/app/static/vendor ./app/static/vendor
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--limit-concurrency", "64"]

FROM base AS worker
# The validated target is Linux x86_64, Blender 4.5.3 LTS, CPU rendering.
ARG BLENDER_VERSION=4.5.3
ARG BLENDER_SHA256=975c58fcb244273838534bba771e64ad87739216b0f9b39a888531a49a72d845
RUN apt-get update && apt-get install -y --no-install-recommends curl xz-utils ca-certificates libx11-6 libxxf86vm1 libxi6 libxfixes3 libxrender1 libgl1 libegl1 libsm6 libxkbcommon0 libdbus-1-3 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 3 "https://download.blender.org/release/Blender4.5/blender-${BLENDER_VERSION}-linux-x64.tar.xz" -o /tmp/blender.tar.xz \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum --check \
    && mkdir /opt/blender && tar -xJf /tmp/blender.tar.xz --strip-components=1 -C /opt/blender && rm /tmp/blender.tar.xz
COPY worker ./worker
ENV BLENDER_BIN=/opt/blender/blender
USER 10001:10001
CMD ["python", "-m", "worker.runner"]
