"""Cloudflare R2 artifact storage."""

import os
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv

_REQUIRED_ENV = ("R2_AK", "R2_SK", "R2_ENDPOINT", "R2_BUCKET")


def _configuration() -> dict[str, str] | None:
    load_dotenv()
    values = {name: os.getenv(name, "").strip() for name in _REQUIRED_ENV}
    if not all(values.values()):
        return None
    return values


def upload_to_r2(file: Path, object_name: str | None = None) -> str | None:
    """Upload *file* to R2 and return its object key.

    Storage is optional: ``None`` is returned when any required R2 setting is
    absent. Upload errors are raised so callers can log and isolate them.
    """
    path = Path(file)
    if not path.is_file():
        raise FileNotFoundError(path)

    config = _configuration()
    if config is None:
        return None

    key = (object_name or path.name).replace("\\", "/").lstrip("/")
    client: Any = boto3.client(
        service_name="s3",
        endpoint_url=config["R2_ENDPOINT"],
        aws_access_key_id=config["R2_AK"],
        aws_secret_access_key=config["R2_SK"],
        region_name="auto",
    )
    client.upload_file(str(path), config["R2_BUCKET"], key)
    return key
