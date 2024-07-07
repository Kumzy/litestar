from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr

from litestar.middleware.session.server_side import ServerSideSessionBackend, ServerSideSessionConfig
from litestar.security.session_auth import SessionAuth

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection


class User(BaseModel):
    id: UUID
    name: str
    email: EmailStr


user_instance = UserFactory.build()


def retrieve_user_handler(session_data: Dict[str, Any], _: "ASGIConnection") -> Optional[User]:
    if session_data["id"] == str(user_instance.id):
        return User(**session_data)
    return None


session_auth = SessionAuth[User, ServerSideSessionBackend](
    retrieve_user_handler=retrieve_user_handler,
    # we must pass a config for a session backend.
    # all session backends are supported
    session_backend_config=ServerSideSessionConfig(),
    # exclude any URLs that should not have authentication.
    # We exclude the documentation URLs, signup and login.
    exclude=["/login", "/signup", "/schema"],
)
