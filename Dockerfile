FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_APP=wsgi.py

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 webinar

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p instance backups logs && chown -R webinar:webinar /app
USER webinar

EXPOSE 8000
# Migrasi dijalankan saat start agar skema selalu terbaru.
CMD ["sh", "-c", "flask db upgrade && gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 2 --threads 4 --access-logfile -"]
