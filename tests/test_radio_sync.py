"""Tests for radio_sync module.

These tests verify the polling pause mechanism that prevents
message polling from interfering with repeater CLI operations.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.radio_sync import (
    _polling_pause_count,
    is_polling_paused,
    pause_polling,
    sync_radio_time,
)


@pytest.fixture(autouse=True)
def reset_polling_state():
    """Reset polling pause state before and after each test."""
    import app.radio_sync as radio_sync
    radio_sync._polling_pause_count = 0
    yield
    radio_sync._polling_pause_count = 0


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
