from litestar import Litestar


async def some_dependency() -> str: ...


app = Litestar(dependencies={"some": some_dependency})
