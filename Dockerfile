# TableOrder - production container (Render / Railway / Fly / any Docker host)
FROM python:3.11-slim

# Keep Python lean and unbuffered for cloud logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app.
COPY . .

# Cloud platforms set PORT; default to 8000 for local docker run.
EXPOSE 8000

# Shell form so ${PORT:-8000} is expanded at runtime.
CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000}