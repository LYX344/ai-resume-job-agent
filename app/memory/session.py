from app.models.chat import ChatMessage
from app.models.session import SessionState


MAX_SESSION_MESSAGES = 20


def append_session_turn(
    session: SessionState,
    *,
    user_message: str,
    assistant_message: str,
    max_messages: int = MAX_SESSION_MESSAGES,
) -> SessionState:
    messages = [
        *session.messages,
        ChatMessage(role="user", content=user_message),
        ChatMessage(role="assistant", content=assistant_message),
    ]
    return SessionState(
        session_id=session.session_id,
        messages=messages[-max_messages:],
    )
