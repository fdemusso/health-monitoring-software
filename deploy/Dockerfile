# The live backend (WebSocket bridge) for the dashboard: `ares3 serve`. Built from the repository root:
#   docker compose -f deploy/docker-compose.yml build
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Editable install, as in the root Dockerfile: models/ and scenarios/ are found from the repository root (/app).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[serve,ml]"

# What the simulation needs to run: the generated station and the models (joblib runs code on load: only these, our own).
COPY scenarios ./scenarios
COPY models ./models

RUN useradd --system --no-create-home ares
USER ares

EXPOSE 8765
ENTRYPOINT ["ares3"]
