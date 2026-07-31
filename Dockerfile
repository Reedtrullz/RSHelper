# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ARG VERSION=local
ENV PYTHONPATH=/app/src \
    VERSION=${VERSION} \
    HOME=/home/rshelper

RUN useradd --create-home --shell /usr/sbin/nologin rshelper

WORKDIR /app
COPY src ./src

USER rshelper
EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5555/api/health', timeout=5).status == 200 else 1)"

CMD ["python", "-m", "rshelper", "dashboard", "--bind", "0.0.0.0", "--port", "5555"]
