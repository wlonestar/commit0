"""Object storage service integrations."""

from services.s3.r2 import upload_to_r2

__all__ = [
    "upload_to_r2"
]
