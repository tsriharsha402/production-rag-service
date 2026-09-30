FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[redis,ui]"

COPY data ./data
COPY ui ./ui

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "rag_service.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
