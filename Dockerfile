# One image for the platform and the demo bank: same code base, different command.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sentineldesk ./sentineldesk
COPY bank ./bank
COPY scripts ./scripts
COPY runbooks ./runbooks
COPY faq ./faq

# The dataset is downloaded and the triage model trained while building the image,
# so a container starts ready to classify.
RUN python -m scripts.fetch_data && python -m scripts.train

ENV DATABASE_URL=sqlite:////data/sentineldesk.sqlite3
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "sentineldesk.api:app", "--host", "0.0.0.0", "--port", "8000"]
