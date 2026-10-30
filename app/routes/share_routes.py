from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.services.share_service import share_service

router = APIRouter(prefix="/share", tags=["Sharing"])


@router.get("/{token}")
def public_progress(token: str):
    """Public, unauthenticated, read-only. Unknown and revoked tokens look identical."""
    data = share_service.public_view(token)
    if data is None:
        raise HTTPException(status_code=404, detail="This shared page does not exist or has been turned off.")
    return JSONResponse(data, headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"})
