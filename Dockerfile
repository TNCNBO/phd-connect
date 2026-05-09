# Stage 1: Install dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Stage 2: Runtime
FROM python:3.13-slim-bookworm
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["python", "main.py"]
