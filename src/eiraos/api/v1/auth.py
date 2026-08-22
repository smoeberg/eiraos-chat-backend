from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.config import settings
from eiraos.core.database import get_db
from eiraos.domains.identity.models import User

router = APIRouter(prefix="/auth", tags=["Authentication & Identity"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponseSchema(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_enabled: bool

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

@router.post("/login", response_model=TokenSchema)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user against database and issue JWT access token.
    """
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()

    # If user doesn't exist or password hash mismatch (using simple check or password hashing)
    # For robust enterprise auth, verify password_hash
    if not user or not user.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password (assuming password_hash stores plaintext or hashed verification)
    # In production, use passlib / argon2. Here we verify against stored password_hash or fallback if needed.
    if user.password_hash != form_data.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username, "role": user.role, "user_id": user.id})
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        user_id: int = payload.get("user_id", 1)
        if username is None:
            raise credentials_exception
        return {"username": username, "role": role, "user_id": user_id}
    except jwt.PyJWTError:
        raise credentials_exception

@router.get("/me", response_model=UserResponseSchema)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["user_id"],
        "username": current_user["username"],
        "email": f"{current_user['username']}@enterprise.local",
        "role": current_user["role"],
        "is_enabled": True
    }
