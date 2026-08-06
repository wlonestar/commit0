# IF you change the base image, you need to rebuild all images (run with --force_rebuild)
_DOCKERFILE_BASE = r"""
FROM --platform={platform} ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Fix DNS and install base packages in a single RUN (DNS changes don't persist across RUNs)
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 114.114.114.114" >> /etc/resolv.conf && \
    apt update && apt install -y \
wget \
build-essential \
libffi-dev \
libtiff-dev \
python3 \
python3-pip \
python-is-python3 \
jq \
curl \
locales \
locales-all \
tzdata \
&& rm -rf /var/lib/apt/lists/*

# Fix DNS for subsequent RUNs and install Git
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 114.114.114.114" >> /etc/resolv.conf && \
    apt-get update && apt-get install software-properties-common -y && \
    add-apt-repository ppa:git-core/ppa -y && \
    apt-get update && apt-get install git -y

# Fix DNS and install curl/ca-certificates for uv installer
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 114.114.114.114" >> /etc/resolv.conf && \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin:/root/.cargo/bin/:$PATH"
"""

_DOCKERFILE_REPO = r"""FROM --platform={platform} commit0.base:latest

COPY ./setup.sh /root/
RUN chmod +x /root/setup.sh
RUN /bin/bash /root/setup.sh

WORKDIR /testbed/

# Automatically activate the testbed environment
RUN echo "source /testbed/.venv/bin/activate" > /root/.bashrc
"""


def get_dockerfile_base(platform: str) -> str:
    return _DOCKERFILE_BASE.format(platform=platform)


def get_dockerfile_repo(platform: str) -> str:
    return _DOCKERFILE_REPO.format(platform=platform)


__all__ = []
