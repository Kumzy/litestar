from litestar import get


@get("/")
def index(param: int = Parameter(gt=5)) -> dict[str, int]: ...
