import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import AppSettings, BotConfig
from app.repository import AppSettingsRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


def validate_bot_code(code: str, bot_name: str | None = None) -> None:
    """Validate bot code syntax. Raises HTTPException on error."""
    if not code or not code.strip():
        return  # Empty code is valid (disables bot)

    try:
        compile(code, "<bot_code>", "exec")
    except SyntaxError as e:
        name_part = f"'{bot_name}' " if bot_name else ""
        raise HTTPException(
            status_code=400,
            detail=f"Bot {name_part}has syntax error at line {e.lineno}: {e.msg}",
        ) from None


def validate_all_bots(bots: list[BotConfig]) -> None:
    """Validate all bots' code syntax. Raises HTTPException on first error."""
    for bot in bots:
        validate_bot_code(bot.code, bot.name)


class AppSettingsUpdate(BaseModel):
    max_radio_contacts: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description=(
            "Maximum contacts to keep on radio (favorites first, then recent non-repeaters)"
        ),
    )
    auto_decrypt_dm_on_advert: bool | None = Field(
        default=None,
        description="Whether to attempt historical DM decryption on new contact advertisement",
    )
    sidebar_sort_order: Literal["recent", "alpha"] | None = Field(
        default=None,
        description="Sidebar sort order: 'recent' or 'alpha'",
    )
    advert_interval: int | None = Field(
        default=None,
        ge=0,
        description="Periodic advertisement interval in seconds (0 = disabled)",
    )
    bots: list[BotConfig] | None = Field(
        default=None,
        description="List of bot configurations",
    )


class FavoriteRequest(BaseModel):
    type: Literal["channel", "contact"] = Field(description="'channel' or 'contact'")
    id: str = Field(description="Channel key or contact public key")


class MigratePreferencesRequest(BaseModel):
    favorites: list[FavoriteRequest] = Field(
        default_factory=list,
        description="List of favorites from localStorage",
    )
    sort_order: str = Field(
        default="recent",
        description="Sort order preference from localStorage",
    )
    last_message_times: dict[str, int] = Field(
        default_factory=dict,
        description="Map of conversation state keys to timestamps from localStorage",
    )


class MigratePreferencesResponse(BaseModel):
    migrated: bool = Field(description="Whether migration occurred (false if already migrated)")
    settings: AppSettings = Field(description="Current settings after migration attempt")


@router.get("", response_model=AppSettings)
async def get_settings() -> AppSettings:
    """Get current application settings."""
    return await AppSettingsRepository.get()


@router.patch("", response_model=AppSettings)
async def update_settings(update: AppSettingsUpdate) -> AppSettings:
    """Update application settings.

    Settings are persisted to the database and survive restarts.
    """
    kwargs = {}
    if update.max_radio_contacts is not None:
        logger.info("Updating max_radio_contacts to %d", update.max_radio_contacts)
        kwargs["max_radio_contacts"] = update.max_radio_contacts

    if update.auto_decrypt_dm_on_advert is not None:
        logger.info("Updating auto_decrypt_dm_on_advert to %s", update.auto_decrypt_dm_on_advert)
        kwargs["auto_decrypt_dm_on_advert"] = update.auto_decrypt_dm_on_advert

    if update.sidebar_sort_order is not None:
        logger.info("Updating sidebar_sort_order to %s", update.sidebar_sort_order)
        kwargs["sidebar_sort_order"] = update.sidebar_sort_order

    if update.advert_interval is not None:
        logger.info("Updating advert_interval to %d", update.advert_interval)
        kwargs["advert_interval"] = update.advert_interval

    if update.bots is not None:
        validate_all_bots(update.bots)
        logger.info("Updating bots (count=%d)", len(update.bots))
        kwargs["bots"] = update.bots

    if kwargs:
        return await AppSettingsRepository.update(**kwargs)

    return await AppSettingsRepository.get()


@router.post("/favorites/toggle", response_model=AppSettings)
async def toggle_favorite(request: FavoriteRequest) -> AppSettings:
    """Toggle a conversation's favorite status."""
    settings = await AppSettingsRepository.get()
    is_favorited = any(f.type == request.type and f.id == request.id for f in settings.favorites)

    if is_favorited:
        logger.info("Removing favorite: %s %s", request.type, request.id[:12])
        return await AppSettingsRepository.remove_favorite(request.type, request.id)
    else:
        logger.info("Adding favorite: %s %s", request.type, request.id[:12])
        return await AppSettingsRepository.add_favorite(request.type, request.id)


@router.post("/migrate", response_model=MigratePreferencesResponse)
async def migrate_preferences(request: MigratePreferencesRequest) -> MigratePreferencesResponse:
    """Migrate all preferences from frontend localStorage to database.

    This is a one-time migration. If preferences have already been migrated,
    this endpoint will not overwrite them and will return migrated=false.

    Call this on frontend startup to ensure preferences are moved to the database.
    After successful migration, the frontend should clear localStorage preferences.

    Migrates:
    - favorites (remoteterm-favorites)
    - sort_order (remoteterm-sortOrder)
    - last_message_times (remoteterm-lastMessageTime)
    """
    # Convert to dict format for the repository method
    frontend_favorites = [{"type": f.type, "id": f.id} for f in request.favorites]

    settings, did_migrate = await AppSettingsRepository.migrate_preferences_from_frontend(
        favorites=frontend_favorites,
        sort_order=request.sort_order,
        last_message_times=request.last_message_times,
    )

    if did_migrate:
        logger.info(
            "Migrated preferences from frontend: %d favorites, sort_order=%s, %d message times",
            len(frontend_favorites),
            request.sort_order,
            len(request.last_message_times),
        )
    else:
        logger.debug("Preferences already migrated, skipping")

    return MigratePreferencesResponse(
        migrated=did_migrate,
        settings=settings,
    )
