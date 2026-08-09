FROM python:3.12-slim

WORKDIR /app

# ==========================================
# System dependencies
# ==========================================

RUN apt-get update \
    && apt-get install -y \
        ffmpeg \
        curl \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*


# ==========================================
# Install Deno
# ==========================================

RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno
ENV PATH="${DENO_INSTALL}/bin:${PATH}"


# ==========================================
# Python dependencies
# ==========================================

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ==========================================
# Application
# ==========================================

COPY . .

RUN mkdir -p /app/downloads


# ==========================================
# Render
# ==========================================

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
