"""Optional persistence and notification services for benchmark runs."""

from services.completion import CompletionResult, store_and_notify
from services.notice import send_notice
from services.s3 import upload_to_r2

__all__ = [
    "CompletionResult",
    "send_notice",
    "store_and_notify",
    "upload_to_r2",
]
