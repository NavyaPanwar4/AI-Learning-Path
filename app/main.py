from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from uuid import uuid4
from app.routes import auth_routes, chat_routes, user_routes, roadmap_routes, learning_routes, admin_routes, share_routes
from app.services.reminder_email_service import reminder_poller
from app.services.chat_history_retention_service import chat_history_retention_poller
from app.services.llm_service import LLMError
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.rate_limit import RequestRateLimitMiddleware

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Traject API for personalized, adaptive learning paths and progress-aware learning support.",
    version="1.0.0"
)

app.add_middleware(RequestRateLimitMiddleware)

allowed_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Global handler: ensures CORS headers are present even on unhandled 500 errors.
# Without this, FastAPI exceptions bypass CORS middleware and browser sees no header.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    logger.error("Unhandled exception on %s [%s]: %s", request.url, getattr(request.state, "request_id", "unknown"), exc)
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )

@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)}, headers=headers)

@app.on_event("startup")
def startup_event():
    logger.info("Starting up Traject API...")
    reminder_poller.start()  # no-op unless REMINDER_EMAILS_ENABLED and SMTP_HOST are set
    chat_history_retention_poller.start()

@app.on_event("shutdown")
def shutdown_event():
    chat_history_retention_poller.stop()

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "service": settings.PROJECT_NAME}

# Include routers
app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(roadmap_routes.router)
app.include_router(chat_routes.router)
app.include_router(learning_routes.router)
app.include_router(share_routes.router)
app.include_router(admin_routes.router)

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on port 8000 via main execution")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
