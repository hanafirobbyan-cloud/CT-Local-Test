"""Entry point WSGI: `gunicorn wsgi:app` (produksi) atau `flask --app wsgi run` (development)."""
from app import create_app

app = create_app()
