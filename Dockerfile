# ---- Builder stage ----
FROM python:3.11-slim AS builder

# Install build tools
RUN apt-get update && apt-get install -y \ 
    build-essential cmake git && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN python -m pip install --upgrade uv

# Set workdir
WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN uv pip install -r requirements.txt

# Build SimC binaries for Linux (default target)
RUN cmake -S . -B build -DTARGET_PLATFORM=linux && \
    cmake --build build --target simc-master simc-worker

# ---- Runtime stage ----
# Use shared build script scripts/build_pyinstaller.sh
FROM python:3.11-slim AS runtime

# Create non-root user
RUN useradd -m appuser
USER appuser

WORKDIR /app
ENV HOST=0.0.0.0
ENV PORT=8000
ENV ADMIN_TOKEN=
ENV CLUSTER_SECRET=
ENV SIMC_PATH=
ENV BASE_DIR=
ENV SIMC_HELPER_DEV_MODE=

# Copy built binaries and required files from builder
COPY --from=builder /app/build/simc-master /app/build/simc-worker /usr/local/bin/
COPY --from=builder /app/src /app/src
COPY --from=builder /app/requirements.txt /app/

# Install runtime Python deps (if any)
RUN python -m pip install --no-cache-dir -r requirements.txt

# Expose FastAPI port
EXPOSE 8000
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1

# Set entrypoint to run the FastAPI app (uvicorn)
ENTRYPOINT ["uvicorn", "src.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
