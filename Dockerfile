# Local Compose runtime. Packaged standalone artifacts are built separately via CMake.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . /app
RUN useradd -m appuser && chown -R appuser:appuser /app

USER appuser

ENV HOST=0.0.0.0
ENV PORT=8000
ENV SIMC_HELPER_DEV_MODE=1

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["uvicorn", "src.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
