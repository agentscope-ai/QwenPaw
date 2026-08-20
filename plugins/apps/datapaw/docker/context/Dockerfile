FROM python:3.11-slim

WORKDIR /app

# Install the context service and its CLI companion from PyPI.
RUN pip install --no-cache-dir \
    datapaw-context==0.2.1 \
    datapaw-cli==0.2.0

EXPOSE 8765

CMD ["uvicorn", "context_manager.api.server:app", "--host", "0.0.0.0", "--port", "8765"]
