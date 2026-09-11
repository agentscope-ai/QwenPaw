FROM python:3.11-slim

WORKDIR /app

# The seed container needs the bundled demo assets (qwenpaw-data-context), the CLI
# to import/weave, and psycopg to seed PostgreSQL directly from Python.
RUN pip install --no-cache-dir \
    qwenpaw-data-context==0.1.0 \
    qwenpaw-data-cli==0.1.0 \
    psycopg[binary]

COPY seed.py /seed.py

CMD ["python", "/seed.py"]
