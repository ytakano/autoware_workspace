FROM ubuntu:22.04

ARG USERNAME=user
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y \
      vim \
      build-essential \
      zsh \
      git \
      curl \
      libncurses5-dev \
      libgmp-dev \
      pkg-config \
      ca-certificates \
      libffi-dev \
      libffi8ubuntu1 \
      libgmp10 \
      npm \
      procps \
      clang && \
    rm -rf /var/lib/apt/lists/*

RUN npm i -g @openai/codex

RUN set -eux; \
    OLD_USER_BY_UID="$(getent passwd "${UID}" | cut -d: -f1 || true)"; \
    OLD_GROUP_BY_GID="$(getent group "${GID}" | cut -d: -f1 || true)"; \
    OLD_USER_BY_NAME="$(getent passwd "${USERNAME}" | cut -d: -f1 || true)"; \
    OLD_GROUP_BY_NAME="$(getent group "${USERNAME}" | cut -d: -f1 || true)"; \
    \
    if [ -n "${OLD_USER_BY_UID}" ]; then \
        userdel -r "${OLD_USER_BY_UID}" || userdel "${OLD_USER_BY_UID}" || true; \
    fi; \
    \
    if [ -n "${OLD_USER_BY_NAME}" ] && [ "${OLD_USER_BY_NAME}" != "${OLD_USER_BY_UID}" ]; then \
        userdel -r "${OLD_USER_BY_NAME}" || userdel "${OLD_USER_BY_NAME}" || true; \
    fi; \
    \
    if [ -n "${OLD_GROUP_BY_GID}" ]; then \
        groupdel "${OLD_GROUP_BY_GID}" || true; \
    fi; \
    \
    if [ -n "${OLD_GROUP_BY_NAME}" ] && [ "${OLD_GROUP_BY_NAME}" != "${OLD_GROUP_BY_GID}" ]; then \
        groupdel "${OLD_GROUP_BY_NAME}" || true; \
    fi; \
    \
    groupadd -g "${GID}" "${USERNAME}"; \
    useradd -m -d "/home/${USERNAME}" -s /bin/zsh -u "${UID}" -g "${GID}" "${USERNAME}"; \
    mkdir -p "/home/${USERNAME}"; \
    chown -R "${UID}:${GID}" "/home/${USERNAME}"

COPY zshrc /tmp/.zshrc
COPY zshenv /tmp/.zshenv

RUN cp /tmp/.zshrc "/home/${USERNAME}/.zshrc" && \
    cp /tmp/.zshenv "/home/${USERNAME}/.zshenv" && \
    chown "${UID}:${GID}" "/home/${USERNAME}/.zshrc" "/home/${USERNAME}/.zshenv"

USER ${USERNAME}
WORKDIR /home/${USERNAME}
ENV HOME=/home/${USERNAME}

RUN whoami && id && echo "HOME=$HOME"

RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://gh.io/copilot-install | bash

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

RUN . "/home/${USERNAME}"/.cargo/env && \
    cargo install cargo-binutils && \
    cargo install mdbook-mermaid

CMD ["/bin/zsh"]
