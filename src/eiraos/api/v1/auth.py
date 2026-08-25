from datetime import datetime, timedelta
import asyncio
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt
from passlib.context import CryptContext

from eiraos.core.database import get_db
from eiraos.core.config import settings
from eiraos.core import ratelimit
from eiraos.core.ratelimit import limiter
from eiraos.domains.identity.models import User
from eiraos.domains.organizations.models import Organization, OrganizationMember
from eiraos.domains.governance.capabilities import ROLE_CAPABILITIES
from eiraos.application.authorization import AuthorizationBoundary, AuthorizationDenied

router = APIRouter(prefix="/auth", tags=["Authentication & Identity"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

TOKEN_ISSUER = settings.JWT_ISSUER
TOKEN_AUDIENCE = settings.JWT_AUDIENCE

# Compatibility view for callers that still inspect the legacy mapping. The
# authority source itself now lives in the governance domain.
ROLE_PERMISSIONS = {
    role: tuple(
        capability.value
        for capability in sorted(grants, key=lambda item: item.value)
        if not capability.value.startswith(("provider:", "tool:"))
    )
    for role, grants in ROLE_CAPABILITIES.items()
}

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_enabled: bool

    class Config:
        from_attributes = True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (TypeError, ValueError):
        return False

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


_DUMMY_PASSWORD_HASH = get_password_hash(uuid.uuid4().hex)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "token_version": to_encode.get("token_version", 1),
    })
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(ratelimit.AUTH_REGISTER_LIMIT)
async def register_user(request: Request, payload: UserRegister, db: AsyncSession = Depends(get_db)):
    if not settings.ALLOW_PUBLIC_REGISTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled.",
        )
    result = await db.execute(select(User).where(User.email == payload.email))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        name=payload.full_name,
        username=payload.email,
        password_hash=get_password_hash(payload.password),
        role="member",
        is_enabled=True
    )
    db.add(user)
    await db.flush()

    org_name = f"{payload.email.split('@')[0]}'s Organization"
    org = Organization(name=org_name, slug=org_name.lower().replace(" ", "-"))
    db.add(org)
    await db.flush()

    membership = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role="owner"
    )
    db.add(membership)
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/login", response_model=TokenResponse)
@limiter.limit(ratelimit.AUTH_LOGIN_LIMIT)
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where((User.email == form_data.username) | (User.username == form_data.username)))
    user = result.scalars().first()

    candidate_hash = user.password_hash if user and user.is_enabled and user.password_hash else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(form_data.password, candidate_hash)
    if not user or not user.is_enabled or not user.password_hash or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    org_res = await db.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
    membership = org_res.scalars().first()
    
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no organization membership")

    access_token = create_access_token(data={
        "sub": user.email,
        "user_id": user.id,
        "role": membership.role,
        "organization_id": membership.organization_id,
        "token_version": user.token_version
    })
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    request: Request = None,
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=TOKEN_ISSUER,
            audience=TOKEN_AUDIENCE,
            options={"require": [
                "exp", "iat", "jti", "iss", "aud", "sub", "user_id",
                "organization_id", "token_version",
            ]},
        )
        email = payload.get("sub")
        user_id = payload.get("user_id")
        role: str = payload.get("role", "member")
        org_id = payload.get("organization_id")
        token_version = payload.get("token_version")
        jti = payload.get("jti")

        if (
            not isinstance(email, str) or not email
            or type(user_id) is not int or user_id <= 0
            or type(org_id) is not int or org_id <= 0
            or type(token_version) is not int or token_version <= 0
            or not isinstance(jti, str) or not jti
        ):
            raise credentials_exception

        ctx = {
            "email": email,
            "user_id": user_id,
            "role": role,
            "organization_id": org_id,
            "jti": jti,
            "token_version": token_version,
        }
        if request is not None:
            request.state.organization_id = org_id
            request.state.user_id = user_id
        return ctx
    except jwt.PyJWTError:
        raise credentials_exception

async def get_current_active_organization(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> int:
    org_id = current_user.get("organization_id")
    user_id = current_user.get("user_id")

    if not org_id or not user_id:
        raise HTTPException(status_code=403, detail="Invalid organization context")

    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
    )
    res = await db.execute(stmt)
    membership = res.scalars().first()

    if not membership:
        raise HTTPException(status_code=403, detail="User is not a member of this organization")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_enabled:
        raise HTTPException(status_code=401, detail="Identity is inactive")
    if current_user.get("token_version") != user.token_version:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if request is not None:
        request.state.organization_id = org_id
        request.state.user_id = user_id
    return org_id

def require_permission(required_permission: str):
    """Transport adapter for the single application authorization boundary."""
    async def permission_dependency(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        user_id = current_user.get("user_id")
        org_id = current_user.get("organization_id")
        if not user_id or not org_id:
            raise HTTPException(status_code=403, detail="Invalid organization context")

        try:
            context = await AuthorizationBoundary(db).authorize(
                identity=current_user,
                capability=required_permission,
                resource_organization_id=org_id,
            )
        except AuthorizationDenied:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: missing required permission '{required_permission}'"
            )
        current_user["role"] = context.role
        current_user["authorization"] = context
        return current_user
    return permission_dependency

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _organization_id: int = Depends(get_current_active_organization),
):
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
