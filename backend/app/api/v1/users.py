from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, get_password_hash
from app.models.user import User
from app.schemas.user import UserResponse, UserSettingsUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Retrieve profile and settings for the authenticated user."""
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me/settings",
    response_model=UserResponse,
    summary="Update current user settings and preferences",
)
async def update_settings(
    settings_in: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update user attributes including full name, custom system prompt, or password."""
    if settings_in.full_name is not None:
        current_user.full_name = settings_in.full_name

    if settings_in.custom_system_prompt is not None:
        current_user.custom_system_prompt = settings_in.custom_system_prompt

    if settings_in.password is not None:
        current_user.hashed_password = get_password_hash(settings_in.password)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return UserResponse.model_validate(current_user)
