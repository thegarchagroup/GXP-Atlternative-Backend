FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/uploads && chown -R app:app /app/uploads

USER app
EXPOSE 1802
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:1802/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "1802", "--proxy-headers", "--forwarded-allow-ips", "*"]
