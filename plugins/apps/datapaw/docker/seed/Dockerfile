FROM python:3.11-slim

WORKDIR /app

# The seed container needs the bundled demo assets (datapaw-context), the CLI
# to import/weave, and psycopg to seed PostgreSQL directly from Python.
RUN pip install --no-cache-dir \
    datapaw-context==0.2.1 \
    datapaw-cli==0.2.0 \
    psycopg[binary]

COPY seed.py /seed.py

CMD ["python", "/seed.py"]
