FROM ubuntu:22.04 AS runtime-test

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11-utils xdotool fluxbox fonts-dejavu-core imagemagick \
    && rm -rf /var/lib/apt/lists/*

# Deliberately omit system Python and Tesseract to exercise the bundled runtime.
COPY dist/ConsoleClicker /opt/ConsoleClicker
COPY tests/fixtures /opt/fixtures
COPY scripts/docker/packaged-smoke.sh /opt/packaged-smoke.sh
WORKDIR /opt
CMD ["bash", "/opt/packaged-smoke.sh"]

FROM runtime-test AS source-test
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-tk python3-dev build-essential \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-build.txt /src/
RUN python3 -m venv /opt/test-venv \
    && /opt/test-venv/bin/python -m pip install --no-cache-dir -r /src/requirements-build.txt
COPY clicker /src/clicker
COPY tests /src/tests
COPY launcher.py /src/launcher.py
WORKDIR /src
CMD ["/opt/test-venv/bin/python", "-m", "pytest", "-q", "-rs"]
