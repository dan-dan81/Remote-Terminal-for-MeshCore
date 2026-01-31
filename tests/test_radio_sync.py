"""Tests for radio_sync module.

These tests verify the polling pause mechanism that prevents
message polling from interfering with repeater CLI operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from meshcore import EventType

from app.models import Contact
from app.radio_sync import (
    is_polling_paused,
    pause_polling,
    sync_radio_time,
    sync_recent_contacts_to_radio,
)


@pytest.fixture(autouse=True)
def reset_sync_state():
    """Reset polling pause state and sync timestamp before and after each test."""
    import app.radio_sync as radio_sync

    radio_sync._polling_pause_count = 0
    radio_sync._last_contact_sync = 0.0
    yield
    radio_sync._polling_pause_count = 0
    radio_sync._last_contact_sync = 0.0


class TestPollingPause:
    """Test the polling pause mechanism."""

    def test_initially_not_paused(self):
        """Polling is not paused by default."""
        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_pause_polling_pauses(self):
        """pause_polling context manager pauses polling."""
        assert not is_polling_paused()

        async with pause_polling():
            assert is_polling_paused()

        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_nested_pause_stays_paused(self):
        """Nested pause_polling contexts keep polling paused until all exit."""
        assert not is_polling_paused()

        async with pause_polling():
            assert is_polling_paused()

            async with pause_polling():
                assert is_polling_paused()

            # Still paused - outer context active
            assert is_polling_paused()

        # Now unpaused - all contexts exited
        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_triple_nested_pause(self):
        """Three levels of nesting work correctly."""
        async with pause_polling():
            async with pause_polling():
                async with pause_polling():
                    assert is_polling_paused()
                assert is_polling_paused()
            assert is_polling_paused()
        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_pause_resumes_on_exception(self):
        """Polling resumes even if exception occurs in context."""
        try:
            async with pause_polling():
                assert is_polling_paused()
                raise ValueError("Test error")
        except ValueError:
            pass

        # Should be unpaused despite exception
        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_nested_pause_resumes_correctly_on_inner_exception(self):
        """Nested contexts handle exceptions correctly."""
        async with pause_polling():
            try:
                async with pause_polling():
                    assert is_polling_paused()
                    raise ValueError("Inner error")
            except ValueError:
                pass

            # Outer context still active
            assert is_polling_paused()

        # All contexts exited
        assert not is_polling_paused()

    @pytest.mark.asyncio
    async def test_counter_increments_and_decrements(self):
        """Counter correctly tracks pause depth."""
        import app.radio_sync as radio_sync

        assert radio_sync._polling_pause_count == 0

        async with pause_polling():
            assert radio_sync._polling_pause_count == 1

            async with pause_polling():
                assert radio_sync._polling_pause_count == 2

            assert radio_sync._polling_pause_count == 1

        assert radio_sync._polling_pause_count == 0


class TestSyncRadioTime:
    """Test the radio time sync function."""

    @pytest.mark.asyncio
    async def test_returns_false_when_not_connected(self):
        """sync_radio_time returns False when radio is not connected."""
        with patch("app.radio_sync.radio_manager") as mock_manager:
            mock_manager.meshcore = None
            result = await sync_radio_time()
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """sync_radio_time returns True when time is set successfully."""
        mock_mc = MagicMock()
        mock_mc.commands.set_time = AsyncMock()

        with patch("app.radio_sync.radio_manager") as mock_manager:
            mock_manager.meshcore = mock_mc
            result = await sync_radio_time()

            assert result is True
            mock_mc.commands.set_time.assert_called_once()
            # Verify timestamp is reasonable (within last few seconds)
            call_args = mock_mc.commands.set_time.call_args[0][0]
            import time

            assert abs(call_args - int(time.time())) < 5

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        """sync_radio_time returns False and doesn't raise on error."""
        mock_mc = MagicMock()
        mock_mc.commands.set_time = AsyncMock(side_effect=Exception("Radio error"))

        with patch("app.radio_sync.radio_manager") as mock_manager:
            mock_manager.meshcore = mock_mc
            result = await sync_radio_time()

            assert result is False


KEY_A = "aa" * 32
KEY_B = "bb" * 32


def _make_contact(public_key=KEY_A, name="Alice", on_radio=False, **overrides):
    """Create a Contact model instance for testing."""
    defaults = {
        "public_key": public_key,
        "name": name,
        "type": 0,
        "flags": 0,
        "last_path": None,
        "last_path_len": -1,
        "last_advert": None,
        "lat": None,
        "lon": None,
        "last_seen": None,
        "on_radio": on_radio,
        "last_contacted": None,
        "last_read_at": None,
    }
    defaults.update(overrides)
    return Contact(**defaults)


class TestSyncRecentContactsToRadio:
    """Test the sync_recent_contacts_to_radio function."""

    @pytest.mark.asyncio
    async def test_loads_contacts_not_on_radio(self):
        """Contacts not on radio are added via add_contact."""
        contacts = [_make_contact(KEY_A, "Alice"), _make_contact(KEY_B, "Bob")]

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.type = EventType.OK
        mock_mc.commands.add_contact = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=contacts,
            ),
            patch(
                "app.radio_sync.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ) as mock_set_on_radio,
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            result = await sync_recent_contacts_to_radio()

        assert result["loaded"] == 2
        assert mock_set_on_radio.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_contacts_already_on_radio(self):
        """Contacts already on radio are counted but not re-added."""
        contacts = [_make_contact(KEY_A, "Alice", on_radio=True)]

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=MagicMock())  # Found
        mock_mc.commands.add_contact = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=contacts,
            ),
            patch(
                "app.radio_sync.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ),
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            result = await sync_recent_contacts_to_radio()

        assert result["loaded"] == 0
        assert result["already_on_radio"] == 1
        mock_mc.commands.add_contact.assert_not_called()

    @pytest.mark.asyncio
    async def test_throttled_when_called_quickly(self):
        """Second call within throttle window returns throttled result."""
        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            # First call succeeds
            result1 = await sync_recent_contacts_to_radio()
            assert "throttled" not in result1

            # Second call is throttled
            result2 = await sync_recent_contacts_to_radio()
            assert result2["throttled"] is True
            assert result2["loaded"] == 0

    @pytest.mark.asyncio
    async def test_force_bypasses_throttle(self):
        """force=True bypasses the throttle window."""
        mock_mc = MagicMock()

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            # First call
            await sync_recent_contacts_to_radio()

            # Forced second call is not throttled
            result = await sync_recent_contacts_to_radio(force=True)
            assert "throttled" not in result

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        """Returns error when radio is not connected."""
        with patch("app.radio_sync.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            result = await sync_recent_contacts_to_radio()

        assert result["loaded"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_marks_on_radio_when_found_but_not_flagged(self):
        """Contact found on radio but not flagged gets set_on_radio(True)."""
        contact = _make_contact(KEY_A, "Alice", on_radio=False)

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=MagicMock())  # Found

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=[contact],
            ),
            patch(
                "app.radio_sync.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ) as mock_set_on_radio,
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            result = await sync_recent_contacts_to_radio()

        assert result["already_on_radio"] == 1
        # Should update the flag since contact.on_radio was False
        mock_set_on_radio.assert_called_once_with(KEY_A, True)

    @pytest.mark.asyncio
    async def test_handles_add_failure(self):
        """Failed add_contact increments the failed counter."""
        contacts = [_make_contact(KEY_A, "Alice")]

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.type = EventType.ERROR
        mock_result.payload = {"error": "Radio full"}
        mock_mc.commands.add_contact = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.max_radio_contacts = 200

        with (
            patch("app.radio_sync.radio_manager") as mock_rm,
            patch(
                "app.radio_sync.ContactRepository.get_recent_non_repeaters",
                new_callable=AsyncMock,
                return_value=contacts,
            ),
            patch(
                "app.radio_sync.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ),
            patch(
                "app.radio_sync.AppSettingsRepository.get",
                new_callable=AsyncMock,
                return_value=mock_settings,
            ),
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            result = await sync_recent_contacts_to_radio()

        assert result["loaded"] == 0
        assert result["failed"] == 1
