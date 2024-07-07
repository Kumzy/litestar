from litestar.events import listener
from utils.email import send_email


@listener("user_created", "password_changed")
async def send_email_handler(email: str, message: str) -> None:
    # do something here to send an email

    await send_email(email, message)
