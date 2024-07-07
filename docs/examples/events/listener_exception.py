from dataclasses import dataclass

from litestar import post
from litestar.events import listener
from utils.client import client
from utils.email import send_farewell_email


@listener("user_deleted")
async def send_farewell_email_handler(email: str) -> None:
    await send_farewell_email(email)


@listener("user_deleted")
async def notify_customer_support(reason: str) -> None:
    # do something here to send an email
    await client.post("some-url", reason)


@dataclass
class DeleteUserDTO:
    email: str
    reason: str


@post("/users")
async def delete_user_handler(data: DeleteUserDTO, request: Request) -> None:
    await user_repository.delete({"email": data.email})
    request.app.emit("user_deleted", email=data.email, reason="deleted")
