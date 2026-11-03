FROM python:3.13-slim
ARG RELEASE_ID=development
ENV RELEASE_ID=$RELEASE_ID

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app/backend

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["/app/backend/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
