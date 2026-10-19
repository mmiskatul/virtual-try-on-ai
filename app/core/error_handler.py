import uuid
import time
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("ai_service_error_handler")

def setup_exception_handlers(app: FastAPI):
    """
    Register graceful global exception handlers for FastAPI.
    Prevents unhandled exceptions from crashing the process or leaking internal stack traces,
    secrets, file paths, or system internals to clients.
    """
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Handle 404 endpoint not found
        if exc.status_code == 404 and (exc.detail == "Not Found" or not exc.detail):
            return JSONResponse(
                status_code=404,
                content={
                    "error": "NotFoundError",
                    "code": "ROUTE_NOT_FOUND",
                    "message": f"Cannot {request.method} {request.url.path}. Endpoint does not exist."
                }
            )
        
        # Preserve FastAPI's native HTTPException detail format
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

    async def handle_500(request: Request, exc: Exception):
        error_id = f"err_{uuid.uuid4().hex[:8]}"
        
        # Log internal error securely on the server with request context
        logger.error(
            f"[AI_SERVICE_SERVER_ERROR] [{error_id}] {request.method} {request.url.path} -> {str(exc)}",
            exc_info=True
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please contact system support with this error reference ID.",
                "errorId": error_id,
                "timestamp": int(time.time() * 1000)
            }
        )

    app.add_exception_handler(Exception, handle_500)
    app.add_exception_handler(500, handle_500)
