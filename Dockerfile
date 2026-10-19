FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZENDESK_BASE_URL=https://support.optisigns.com \
    ZENDESK_LOCALE=en-us \
    FILE_SEARCH_STORE=help-center-kb \
    UPLOAD_WORKERS=16 \
    UPLOAD_BATCH=100 \
    LOG_DIR=/app/runs

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ tools/
COPY main.py ask.py check_store.py ./

RUN useradd --create-home --uid 10001 app && mkdir -p /app/runs && chown -R app /app
USER app

# `docker run -e API_KEY=... <image>` runs the sync once and exits 0;
# `docker run ... <image> ask.py "question"` runs the sanity check instead.
ENTRYPOINT ["python"]
CMD ["main.py"]
