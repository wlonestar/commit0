"""Notification service integrations."""

from services.notice.bark import send_notice

__all__ = [
    "send_notice",
]
