# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS application
LABEL org.opencontainers.image.source="https://github.com/fisherpaykel/fpa-ai-ecn-checker"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --create-home --uid 10001 app \
    && mkdir -p /app/out/context_engine \
    && chown -R app:app /app/out

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app scripts/ ./scripts/
COPY --chown=app:app data/Part_Master.csv data/ecn_history.csv ./data/
COPY --chown=app:app docs/rules_list.json ./docs/
COPY --from=frontend-build --chown=app:app /build/dist ./frontend/dist

USER app
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "scripts.app:app"]
