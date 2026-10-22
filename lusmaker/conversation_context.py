"""Context shared by the current conversational request."""

from contextvars import ContextVar

USER_TEXT: ContextVar[str | None] = ContextVar("lusmaker_chat_user_text", default=None)
