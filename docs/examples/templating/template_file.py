from litestar import get
from litestar.response import Template


@get()
async def example() -> Template:
    return Template(template_name="test.html", context={"hello": "world"})
