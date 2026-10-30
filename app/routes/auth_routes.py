from fastapi import APIRouter, HTTPException, Depends, Cookie, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from app.models.schemas import UserCreate, UserLogin, Token, ForgotPasswordRequest, ResetPasswordRequest
from app.services.auth_service import auth_service
from app.utils.security import decode_access_token
from app.utils.config import settings
import logging

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("learning_path_generator")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-form", auto_error=False)

async def get_current_user(header_token: str = Depends(oauth2_scheme), cookie_token: str = Cookie(None, alias="access_token")) -> str:
    token = cookie_token or header_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token or expired token.")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token.")
    
    # check if user exists
    user = auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
        
    return user_id

def _set_auth_cookie(response: Response, token: Token):
    response.set_cookie("access_token", token.access_token, httponly=True,
                        secure=settings.ENVIRONMENT.lower() not in {"development", "test"},
                        samesite="lax", max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

@router.post("/register", response_model=Token)
def register(user: UserCreate, response: Response):
    try:
        token = auth_service.register_user(user)
        _set_auth_cookie(response, token)
        return token
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/login", response_model=Token)
def login(user: UserLogin, response: Response):
    try:
        token = auth_service.authenticate_user(user)
        _set_auth_cookie(response, token)
        return token
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/login-form", response_model=Token, include_in_schema=False)
def login_form(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        user_login = UserLogin(username=form_data.username, password=form_data.password)
        token = auth_service.authenticate_user(user_login)
        if response:
            _set_auth_cookie(response, token)
        return token
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    try:
        auth_service.request_password_reset(request.email)
    except Exception as e:
        logger.error(f"Forgot-password error: {e}")
    return {"message": "If an account with that email exists, a reset link has been sent."}

@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    try:
        auth_service.reset_password(request.token, request.new_password)
        return {"message": "Password reset successful. You can now log in."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Reset-password error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Signed out."}
