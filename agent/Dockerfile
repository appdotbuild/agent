FROM alpine:3.21.3

RUN apk --update add curl python3

RUN curl -fsSL https://astral.sh/uv/install.sh | XDG_BIN_HOME=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

RUN curl -fsSL https://dl.dagger.io/dagger/install.sh | BIN_DIR=$HOME/.local/bin sh

WORKDIR /app

COPY . /app

RUN uv venv

ENTRYPOINT ["uv", "run", "main.py", "--port", "8000"]