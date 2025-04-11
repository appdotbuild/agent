FROM alpine:3.21.3 AS prod

RUN apk add --update --no-cache curl python3
RUN curl -fsSL https://astral.sh/uv/install.sh | XDG_BIN_HOME=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
RUN curl -fsSL https://dl.dagger.io/dagger/install.sh | BIN_DIR=/usr/local/bin sh

WORKDIR /app

COPY pyproject.toml ./
RUN uv venv && uv sync --compile-bytecode
# should be cacheable

COPY . /app

EXPOSE 8001
ENV PYTHONPATH=/app
ENTRYPOINT ["uv", "run", "api/agent_server/async_server.py"]

FROM prod AS dev
WORKDIR /app

RUN uv sync --dev --compile-bytecode
CMD ["uv", "run", "pytest", ".", "--co"]
