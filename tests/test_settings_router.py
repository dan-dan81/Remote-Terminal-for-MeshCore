"""Tests for settings router endpoints and validation behavior."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models import AppSettings, BotConfig, Favorite
from app.routers.settings import (
    AppSettingsUpdate,
    FavoriteRequest,
    MigratePreferencesRequest,
    migrate_preferences,
    toggle_favorite,
    update_settings,
)


def _settings(
    *,
    favorites: list[Favorite] | None = None,
    migrated: bool = False,
    max_radio_contacts: int = 200,
    experimental_channel_double_send: bool = False,
) -> AppSettings:
    return AppSettings(
        max_radio_contacts=max_radio_contacts,
        experimental_channel_double_send=experimental_channel_double_send,
        favorites=favorites or [],
        auto_decrypt_dm_on_advert=False,
        sidebar_sort_order="recent",
        last_message_times={},
        preferences_migrated=migrated,
        advert_interval=0,
        last_advert_time=0,
        bots=[],
    )


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_forwards_only_provided_fields(self):
        updated = _settings(max_radio_contacts=321)
        with patch(
            "app.routers.settings.AppSettingsRepository.update",
            new_callable=AsyncMock,
            return_value=updated,
        ) as mock_update:
            result = await update_settings(
                AppSettingsUpdate(
                    max_radio_contacts=321,
                    advert_interval=3600,
                    experimental_channel_double_send=True,
                )
            )

        assert result.max_radio_contacts == 321
        assert mock_update.call_count == 1
        assert mock_update.call_args.kwargs == {
            "max_radio_contacts": 321,
            "advert_interval": 3600,
            "experimental_channel_double_send": True,
        }

    @pytest.mark.asyncio
    async def test_empty_patch_returns_current_settings(self):
        current = _settings()
        with (
            patch(
                "app.routers.settings.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=current,
            ) as mock_get,
            patch(
                "app.routers.settings.AppSettingsRepository.update",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            result = await update_settings(AppSettingsUpdate())

        assert result == current
        mock_get.assert_awaited_once()
        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_bot_syntax_returns_400(self):
        bad_bot = BotConfig(
            id="bot-1",
            name="BadBot",
            enabled=True,
            code="def bot(:\n    return 'x'\n",
        )

        with pytest.raises(HTTPException) as exc:
            await update_settings(AppSettingsUpdate(bots=[bad_bot]))

        assert exc.value.status_code == 400
        assert "syntax error" in exc.value.detail.lower()


class TestToggleFavorite:
    @pytest.mark.asyncio
    async def test_adds_when_not_favorited(self):
        initial = _settings(favorites=[])
        updated = _settings(favorites=[Favorite(type="contact", id="aa" * 32)])
        request = FavoriteRequest(type="contact", id="aa" * 32)

        with (
            patch(
                "app.routers.settings.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=initial,
            ),
            patch(
                "app.routers.settings.AppSettingsRepository.add_favorite",
                new_callable=AsyncMock,
                return_value=updated,
            ) as mock_add,
            patch(
                "app.routers.settings.AppSettingsRepository.remove_favorite",
                new_callable=AsyncMock,
            ) as mock_remove,
        ):
            result = await toggle_favorite(request)

        assert result.favorites == updated.favorites
        mock_add.assert_awaited_once_with("contact", "aa" * 32)
        mock_remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removes_when_already_favorited(self):
        initial = _settings(favorites=[Favorite(type="channel", id="ABCD")])
        updated = _settings(favorites=[])
        request = FavoriteRequest(type="channel", id="ABCD")

        with (
            patch(
                "app.routers.settings.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=initial,
            ),
            patch(
                "app.routers.settings.AppSettingsRepository.remove_favorite",
                new_callable=AsyncMock,
                return_value=updated,
            ) as mock_remove,
            patch(
                "app.routers.settings.AppSettingsRepository.add_favorite",
                new_callable=AsyncMock,
            ) as mock_add,
        ):
            result = await toggle_favorite(request)

        assert result.favorites == []
        mock_remove.assert_awaited_once_with("channel", "ABCD")
        mock_add.assert_not_awaited()


class TestMigratePreferences:
    @pytest.mark.asyncio
    async def test_maps_frontend_payload_and_returns_migrated_true(self):
        request = MigratePreferencesRequest(
            favorites=[FavoriteRequest(type="contact", id="aa" * 32)],
            sort_order="alpha",
            last_message_times={"contact-aaaaaaaaaaaa": 123},
        )
        settings = _settings(favorites=[Favorite(type="contact", id="aa" * 32)], migrated=True)

        with patch(
            "app.routers.settings.AppSettingsRepository.migrate_preferences_from_frontend",
            new_callable=AsyncMock,
            return_value=(settings, True),
        ) as mock_migrate:
            response = await migrate_preferences(request)

        assert response.migrated is True
        assert response.settings == settings
        assert mock_migrate.call_args.kwargs == {
            "favorites": [{"type": "contact", "id": "aa" * 32}],
            "sort_order": "alpha",
            "last_message_times": {"contact-aaaaaaaaaaaa": 123},
        }

    @pytest.mark.asyncio
    async def test_returns_migrated_false_when_already_done(self):
        request = MigratePreferencesRequest(
            favorites=[],
            sort_order="recent",
            last_message_times={},
        )
        settings = _settings(migrated=True)

        with patch(
            "app.routers.settings.AppSettingsRepository.migrate_preferences_from_frontend",
            new_callable=AsyncMock,
            return_value=(settings, False),
        ):
            response = await migrate_preferences(request)

        assert response.migrated is False
        assert response.settings.preferences_migrated is True
