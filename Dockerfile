FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPA_SERVICE_KIND=api

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data ./data
COPY app.py ./app.py
RUN python -m pip install --upgrade pip && python -m pip install ".[postgres]"

RUN mkdir -p /app/data/runtime /app/data/index /app/exports && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; ui=os.getenv('MPA_SERVICE_KIND')=='ui'; port=os.getenv('PORT', '8501' if ui else '8000'); path='/_stcore/health' if ui else '/health'; urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=3)"

CMD ["uvicorn", "manufacturing_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
