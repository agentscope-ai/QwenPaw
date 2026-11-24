FROM python:3.11-slim

WORKDIR /app

# Install the context service and its CLI companion from PyPI.
RUN pip install --no-cache-dir \
    qwenpaw-data-context==0.4.1 \
    qwenpaw-data-cli==0.4.1

EXPOSE 8765

CMD ["uvicorn", "context_manager.api.server:app", "--host", "0.0.0.0", "--port", "8765"]
