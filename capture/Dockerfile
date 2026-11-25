FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && mkdir -p /captures \
    && chmod 0777 /captures

ENV CAPTURE_DIR=/captures \
    PYTHONUNBUFFERED=1

VOLUME ["/captures"]
ENTRYPOINT ["climate-manager-record"]
