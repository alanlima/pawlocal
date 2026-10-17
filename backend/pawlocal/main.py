from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from pawlocal.api.routes import router
from pawlocal.config import settings

app = FastAPI(title="PawLocal API", version="0.1.0")
app.include_router(router, prefix=settings.api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "bad_request", "message": "Invalid request parameters"},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        content = detail
    else:
        content = {"code": "http_error", "message": "Request could not be completed"}
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.headers
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
