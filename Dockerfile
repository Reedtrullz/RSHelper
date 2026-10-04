# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE_DIGEST=sha256:922f47525757de33aff59f24cdfc85f412ac4a06aa8af7c7e9028d584b7bcdeb
FROM python:3.11-slim@${BASE_IMAGE_DIGEST}

ARG VERSION=local
ARG BASE_IMAGE_DIGEST
ARG TARGETPLATFORM
ENV PYTHONPATH=/app/src \
    VERSION=${VERSION} \
    RSHELPER_BASE_IMAGE_DIGEST=${BASE_IMAGE_DIGEST} \
    RSHELPER_BUILD_PLATFORM=${TARGETPLATFORM} \
    HOME=/home/rshelper

RUN useradd --create-home --shell /usr/sbin/nologin rshelper

WORKDIR /app
COPY src ./src
RUN python - <<'PY'
import json, os, re
from pathlib import Path
version = os.environ['VERSION']
path = Path('/app/src/rshelper/_build.json')
path.unlink(missing_ok=True)
if version != 'local':
    assert re.fullmatch('[0-9a-f]{40}', version), 'full source revision required'
    assert re.fullmatch('sha256:[0-9a-f]{64}', os.environ.get('RSHELPER_BASE_IMAGE_DIGEST', ''))
    assert os.environ['RSHELPER_BUILD_PLATFORM'] == 'linux/amd64', 'production platform must be linux/amd64'
    path.write_text(json.dumps({'schema_version': 1, 'source_revision': version,
        'platform': os.environ['RSHELPER_BUILD_PLATFORM'], 'base_image_digest': os.environ['RSHELPER_BASE_IMAGE_DIGEST']}))
    path.chmod(0o444)
PY

USER rshelper
EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5555/api/health', timeout=5).status == 200 else 1)"

CMD ["python", "-m", "rshelper", "dashboard", "--bind", "0.0.0.0", "--port", "5555"]
