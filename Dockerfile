FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends blender && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY worker ./worker
RUN useradd --create-home --uid 10001 agent && mkdir -p /artifacts && chown agent:agent /artifacts
USER agent
ENV ARTIFACT_ROOT=/artifacts
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
