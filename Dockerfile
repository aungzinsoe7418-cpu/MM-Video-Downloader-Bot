FROM python:3.12-slim

WORKDIR /app

# =========================================================
# System dependencies
# =========================================================

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        unzip \
    && rm -rf /var/lib/apt/lists/*


# =========================================================
# Install Deno
# =========================================================

RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno
ENV PATH="${DENO_INSTALL}/bin:${PATH}"


# =========================================================
# Python dependencies
# =========================================================

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# =========================================================
# Application
# =========================================================

COPY . .

RUN mkdir -p /tmp/mm_video_downloads


# =========================================================
# Environment
# =========================================================

ENV PYTHONUNBUFFERED=1


# =========================================================
# Start
# =========================================================

CMD ["python", "main.py"]
