FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
RUN useradd --system --uid 10001 digest
USER digest

CMD ["python", "-m", "app.main"]
