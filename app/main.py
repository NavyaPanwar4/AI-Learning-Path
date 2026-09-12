from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routes import auth_routes, user_routes, roadmap_routes
from app.utils.config import settings
from app.utils.logger import logger

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Personalized Learning Path Generator. Auto-generates fully personalized learning paths using user profiles and strict LLM extraction orchestration.",
    version="1.0.0"
)

# CORS — allow any localhost port (covers Vite on 5173, 5174, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global handler: ensures CORS headers are present even on unhandled 500 errors.
# Without this, FastAPI exceptions bypass CORS middleware and browser sees no header.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )

@app.on_event("startup")
def startup_event():
    logger.info("Starting up Personalized Learning Path Generator...")

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "service": settings.PROJECT_NAME}

# Include routers
app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(roadmap_routes.router)

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on port 8000 via main execution")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
