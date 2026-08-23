from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.config import settings
from eiraos.core.database import get_db
from eiraos.domains.identity.models import User
from eiraos.domains.organizations.models import OrganizationMember

router = APIRouter(prefix="/auth", tags=["Authentication & Identity"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponseSchema(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_enabled: bool

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

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
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()

    if not user or not user.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check password hash (fall back to plaintext creation if not hashed yet for legacy bootstrap)
    password_valid = False
    if user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$"):
        password_valid = verify_password(form_data.password, user.password_hash)
    else:
        password_valid = (user.password_hash == form_data.password)
        if password_valid:
            # Upgrade to hashed
            user.password_hash = get_password_hash(form_data.password)
            await db.commit()

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch primary organization membership if any
    org_member_res = await db.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
    org_member = org_member_res.scalars().first()
    organization_id = org_member.organization_id if org_member else None

    access_token = create_access_token(data={
        "sub": user.username,
        "role": user.role,
        "user_id": user.id,
        "organization_id": organization_id
    })
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
        organization_id = payload.get("organization_id")
        if username is None:
            raise credentials_exception
        return {"username": username, "role": role, "user_id": user_id, "organization_id": organization_id}
    except jwt.PyJWTError:
        raise credentials_exception

async def get_current_active_organization(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> int:
    """
    Enforces secure tenant isolation by validating that the user is an active member
    of the requested/associated organization. Prevents IDOR and header spoofing.
    """
    org_id = current_user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any organization"
        )
    
    # Verify membership in DB
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == current_user["user_id"],
        OrganizationMember.organization_id == org_id
    )
    res = await db.execute(stmt)
    member = res.scalars().first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this organization"
        )
    return org_id

@router.get("/me", response_model=UserResponseSchema)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["user_id"],
        "username": current_user["username"],
        "email": f"{current_user['username']}@enterprise.local",
        "role": current_user["role"],
        "is_enabled": True
    }
