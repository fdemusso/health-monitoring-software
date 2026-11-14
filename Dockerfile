FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Editable install: the code in /app/src is what runs, so a bind-mounted ./src (docker-compose.yml)
# picks up plugin edits without rebuilding the image.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[dev]"

# Defaults, overridden by the bind mounts in docker-compose.yml.
COPY scenarios ./scenarios
COPY tests ./tests

ENTRYPOINT ["ares3"]
CMD ["--help"]
