"""Tests for event handler logic.

These tests verify the ACK tracking mechanism for direct message
delivery confirmation.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.event_handlers import (
    _active_subscriptions,
    _cleanup_expired_acks,
    _pending_acks,
    register_event_handlers,
    track_pending_ack,
)
from app.repository import AmbiguousPublicKeyPrefixError


@pytest.fixture(autouse=True)
def clear_test_state():
    """Clear pending ACKs and subscriptions before each test."""
    _pending_acks.clear()
    _active_subscriptions.clear()
    yield
    _pending_acks.clear()
    _active_subscriptions.clear()


class TestAckTracking:
    """Test ACK tracking for direct messages."""

    def test_track_pending_ack_stores_correctly(self):
        """Pending ACKs are stored with message ID and timeout."""
        track_pending_ack("abc123", message_id=42, timeout_ms=5000)

        assert "abc123" in _pending_acks
        msg_id, created_at, timeout = _pending_acks["abc123"]
        assert msg_id == 42
        assert timeout == 5000
        assert created_at <= time.time()

    def test_multiple_acks_tracked_independently(self):
        """Multiple pending ACKs can be tracked simultaneously."""
        track_pending_ack("ack1", message_id=1, timeout_ms=1000)
        track_pending_ack("ack2", message_id=2, timeout_ms=2000)
        track_pending_ack("ack3", message_id=3, timeout_ms=3000)

        assert len(_pending_acks) == 3
        assert _pending_acks["ack1"][0] == 1
        assert _pending_acks["ack2"][0] == 2
        assert _pending_acks["ack3"][0] == 3

    def test_cleanup_removes_expired_acks(self):
        """Expired ACKs are removed during cleanup."""
        # Add an ACK that's "expired" (created in the past with short timeout)
        _pending_acks["expired"] = (1, time.time() - 100, 1000)  # Created 100s ago, 1s timeout
        _pending_acks["valid"] = (2, time.time(), 60000)  # Created now, 60s timeout

        _cleanup_expired_acks()

        assert "expired" not in _pending_acks
        assert "valid" in _pending_acks

    def test_cleanup_uses_2x_timeout_buffer(self):
        """Cleanup uses 2x timeout as buffer before expiring."""
        # ACK created 5 seconds ago with 10 second timeout
        # 2x buffer = 20 seconds, so should NOT be expired yet
        _pending_acks["recent"] = (1, time.time() - 5, 10000)

        _cleanup_expired_acks()

        assert "recent" in _pending_acks


class TestAckEventHandler:
    """Test the on_ack event handler."""

    @pytest.mark.asyncio
    async def test_ack_matches_pending_message(self):
        """Matching ACK code updates message and broadcasts."""
        from app.event_handlers import on_ack

        # Setup pending ACK
        track_pending_ack("deadbeef", message_id=123, timeout_ms=10000)

        # Mock dependencies
        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
        ):
            mock_repo.increment_ack_count = AsyncMock(return_value=1)

            # Create mock event
            class MockEvent:
                payload = {"code": "deadbeef"}

            await on_ack(MockEvent())

            # Verify ack count incremented
            mock_repo.increment_ack_count.assert_called_once_with(123)

            # Verify broadcast sent with ack_count
            mock_broadcast.assert_called_once_with(
                "message_acked", {"message_id": 123, "ack_count": 1}
            )

            # Verify pending ACK removed
            assert "deadbeef" not in _pending_acks

    @pytest.mark.asyncio
    async def test_ack_no_match_does_nothing(self):
        """Non-matching ACK code is ignored."""
        from app.event_handlers import on_ack

        track_pending_ack("expected", message_id=1, timeout_ms=10000)

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
        ):
            mock_repo.increment_ack_count = AsyncMock()

            class MockEvent:
                payload = {"code": "different"}

            await on_ack(MockEvent())

            mock_repo.increment_ack_count.assert_not_called()
            mock_broadcast.assert_not_called()
            assert "expected" in _pending_acks

    @pytest.mark.asyncio
    async def test_ack_empty_code_ignored(self):
        """ACK with empty code is ignored."""
        from app.event_handlers import on_ack

        with patch("app.event_handlers.MessageRepository") as mock_repo:
            mock_repo.increment_ack_count = AsyncMock()

            class MockEvent:
                payload = {"code": ""}

            await on_ack(MockEvent())

            mock_repo.increment_ack_count.assert_not_called()


class TestContactMessageCLIFiltering:
    """Test that CLI responses (txt_type=1) are filtered out.

    This prevents duplicate messages when sending CLI commands to repeaters:
    the command endpoint returns the response directly, so we must NOT also
    persist/broadcast it via the normal message handler.
    """

    @pytest.mark.asyncio
    async def test_cli_response_skipped_not_stored(self):
        """CLI responses (txt_type=1) are not stored in database."""
        from app.event_handlers import on_contact_message

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
        ):

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123def456",
                    "text": "clock: 2024-01-01 12:00:00",
                    "txt_type": 1,  # CLI response
                    "sender_timestamp": 1700000000,
                }

            await on_contact_message(MockEvent())

            # Should NOT store in database
            mock_repo.create.assert_not_called()
            # Should NOT broadcast via WebSocket
            mock_broadcast.assert_not_called()
            # Should NOT update contact last_contacted
            mock_contact_repo.update_last_contacted.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_message_schedules_bot_in_background(self):
        """Normal messages should schedule bot execution without blocking."""
        from app.event_handlers import on_contact_message

        def _capture_task(coro):
            coro.close()
            return MagicMock()

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event"),
            patch("app.event_handlers.asyncio.create_task", side_effect=_capture_task) as mock_task,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock) as mock_bot,
        ):
            mock_repo.create = AsyncMock(return_value=42)
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(return_value=None)

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123def456",
                    "text": "Hello, bot",
                    "txt_type": 0,
                    "sender_timestamp": 1700000000,
                }

            await on_contact_message(MockEvent())

            mock_task.assert_called_once()
            mock_bot.assert_called_once()

    @pytest.mark.asyncio
    async def test_normal_message_still_processed(self):
        """Normal messages (txt_type=0) are still processed normally."""
        from app.event_handlers import on_contact_message

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock),
        ):
            mock_repo.create = AsyncMock(return_value=42)
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(return_value=None)

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123def456",
                    "text": "Hello, this is a normal message",
                    "txt_type": 0,  # Normal message (default)
                    "sender_timestamp": 1700000000,
                }

            await on_contact_message(MockEvent())

            # SHOULD store in database
            mock_repo.create.assert_called_once()
            # SHOULD broadcast via WebSocket
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_payload_has_correct_acked_type(self):
        """Broadcast payload should have acked as integer 0, not boolean False."""
        from app.event_handlers import on_contact_message

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock),
        ):
            mock_repo.create = AsyncMock(return_value=42)
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(return_value=None)

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123def456",
                    "text": "Test message",
                    "txt_type": 0,
                    "sender_timestamp": 1700000000,
                }

            await on_contact_message(MockEvent())

            # Verify broadcast was called
            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args

            # First arg is event type, second is payload dict
            event_type, payload = call_args[0]
            assert event_type == "message"
            assert payload["acked"] == 0
            assert payload["acked"] is not False  # Ensure it's int, not bool
            assert isinstance(payload["acked"], int)

    @pytest.mark.asyncio
    async def test_missing_txt_type_defaults_to_normal(self):
        """Messages without txt_type field are treated as normal (not filtered)."""
        from app.event_handlers import on_contact_message

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event"),
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock),
        ):
            mock_repo.create = AsyncMock(return_value=42)
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(return_value=None)

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123def456",
                    "text": "Message without txt_type field",
                    "sender_timestamp": 1700000000,
                    # No txt_type field
                }

            await on_contact_message(MockEvent())

            # SHOULD still be processed (defaults to txt_type=0)
            mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ambiguous_prefix_stores_dm_under_prefix(self):
        """Ambiguous sender prefixes should still be stored under the prefix key."""
        from app.event_handlers import on_contact_message

        with (
            patch("app.event_handlers.MessageRepository") as mock_repo,
            patch("app.event_handlers.ContactRepository") as mock_contact_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
            patch("app.bot.run_bot_for_message", new_callable=AsyncMock),
        ):
            mock_repo.create = AsyncMock(return_value=77)
            mock_contact_repo.get_by_key_or_prefix = AsyncMock(
                side_effect=AmbiguousPublicKeyPrefixError(
                    "abc123",
                    [
                        "abc1230000000000000000000000000000000000000000000000000000000000",
                        "abc123ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                    ],
                )
            )

            class MockEvent:
                payload = {
                    "pubkey_prefix": "abc123",
                    "text": "hello from ambiguous prefix",
                    "txt_type": 0,
                    "sender_timestamp": 1700000000,
                }

            await on_contact_message(MockEvent())

            mock_repo.create.assert_called_once()
            assert mock_repo.create.await_args.kwargs["conversation_key"] == "abc123"

            mock_broadcast.assert_called_once()
            _, payload = mock_broadcast.call_args.args
            assert payload["conversation_key"] == "abc123"


class TestEventHandlerRegistration:
    """Test event handler registration and cleanup."""

    def test_register_handlers_tracks_subscriptions(self):
        """Registering handlers populates _active_subscriptions."""
        mock_meshcore = MagicMock()
        mock_subscription = MagicMock()
        mock_meshcore.subscribe.return_value = mock_subscription

        register_event_handlers(mock_meshcore)

        # Should have 5 subscriptions (one per event type)
        assert len(_active_subscriptions) == 5
        assert mock_meshcore.subscribe.call_count == 5

    def test_register_handlers_twice_does_not_duplicate(self):
        """Calling register_event_handlers twice unsubscribes old handlers first."""
        mock_meshcore = MagicMock()

        # First call: create mock subscriptions
        first_subs = [MagicMock() for _ in range(5)]
        mock_meshcore.subscribe.side_effect = first_subs
        register_event_handlers(mock_meshcore)

        assert len(_active_subscriptions) == 5
        first_sub_objects = list(_active_subscriptions)

        # Second call: create new mock subscriptions
        second_subs = [MagicMock() for _ in range(5)]
        mock_meshcore.subscribe.side_effect = second_subs
        register_event_handlers(mock_meshcore)

        # Old subscriptions should have been unsubscribed
        for sub in first_sub_objects:
            sub.unsubscribe.assert_called_once()

        # Should still have exactly 5 subscriptions (not 10)
        assert len(_active_subscriptions) == 5

        # New subscriptions should be the second batch
        for sub in second_subs:
            assert sub in _active_subscriptions

    def test_register_handlers_clears_before_adding(self):
        """The subscription list is cleared before adding new subscriptions."""
        mock_meshcore = MagicMock()
        mock_meshcore.subscribe.return_value = MagicMock()

        # Pre-populate with stale subscriptions (simulating a bug scenario)
        stale_sub = MagicMock()
        _active_subscriptions.append(stale_sub)
        _active_subscriptions.append(stale_sub)

        register_event_handlers(mock_meshcore)

        # Stale subscriptions should have been unsubscribed
        assert stale_sub.unsubscribe.call_count == 2

        # Should have exactly 5 fresh subscriptions
        assert len(_active_subscriptions) == 5

    def test_register_handlers_survives_unsubscribe_exception(self):
        """If unsubscribe() throws, registration still completes successfully."""
        mock_meshcore = MagicMock()
        mock_meshcore.subscribe.return_value = MagicMock()

        # Create subscriptions where unsubscribe raises an exception
        # (simulates old dispatcher being in a bad state after reconnect)
        bad_sub = MagicMock()
        bad_sub.unsubscribe.side_effect = RuntimeError("Dispatcher is dead")
        _active_subscriptions.append(bad_sub)

        good_sub = MagicMock()
        _active_subscriptions.append(good_sub)

        # Should not raise despite the exception
        register_event_handlers(mock_meshcore)

        # Both unsubscribe methods should have been called
        bad_sub.unsubscribe.assert_called_once()
        good_sub.unsubscribe.assert_called_once()

        # Should have exactly 5 fresh subscriptions
        assert len(_active_subscriptions) == 5


class TestOnPathUpdate:
    """Test the on_path_update event handler."""

    @pytest.mark.asyncio
    async def test_updates_path_for_existing_contact(self):
        """Path is updated when the contact exists in the database."""
        from app.event_handlers import on_path_update

        mock_contact = MagicMock()
        mock_contact.public_key = "aa" * 32

        with patch("app.event_handlers.ContactRepository") as mock_repo:
            mock_repo.get_by_key_prefix = AsyncMock(return_value=mock_contact)
            mock_repo.update_path = AsyncMock()

            class MockEvent:
                payload = {
                    "pubkey_prefix": "aaaaaa",
                    "path": "0102",
                    "path_len": 2,
                }

            await on_path_update(MockEvent())

            mock_repo.get_by_key_prefix.assert_called_once_with("aaaaaa")
            mock_repo.update_path.assert_called_once_with("aa" * 32, "0102", 2)

    @pytest.mark.asyncio
    async def test_does_nothing_when_contact_not_found(self):
        """No update is attempted when the contact is not in the database."""
        from app.event_handlers import on_path_update

        with patch("app.event_handlers.ContactRepository") as mock_repo:
            mock_repo.get_by_key_prefix = AsyncMock(return_value=None)
            mock_repo.update_path = AsyncMock()

            class MockEvent:
                payload = {
                    "pubkey_prefix": "unknown",
                    "path": "0102",
                    "path_len": 2,
                }

            await on_path_update(MockEvent())

            mock_repo.get_by_key_prefix.assert_called_once_with("unknown")
            mock_repo.update_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_defaults_for_missing_payload_fields(self):
        """Missing payload fields fall back to defaults (empty path, -1 length)."""
        from app.event_handlers import on_path_update

        mock_contact = MagicMock()
        mock_contact.public_key = "bb" * 32

        with patch("app.event_handlers.ContactRepository") as mock_repo:
            mock_repo.get_by_key_prefix = AsyncMock(return_value=mock_contact)
            mock_repo.update_path = AsyncMock()

            class MockEvent:
                payload = {}

            await on_path_update(MockEvent())

            mock_repo.get_by_key_prefix.assert_called_once_with("")
            mock_repo.update_path.assert_called_once_with("bb" * 32, "", -1)


class TestOnNewContact:
    """Test the on_new_contact event handler."""

    @pytest.mark.asyncio
    async def test_creates_contact_and_broadcasts(self):
        """Valid new contact is upserted and broadcast via WebSocket."""
        from app.event_handlers import on_new_contact

        with (
            patch("app.event_handlers.ContactRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
            patch("app.event_handlers.time") as mock_time,
        ):
            mock_time.time.return_value = 1700000000
            mock_repo.upsert = AsyncMock()

            class MockEvent:
                payload = {
                    "public_key": "cc" * 32,
                    "adv_name": "Charlie",
                    "type": 1,
                    "flags": 0,
                }

            await on_new_contact(MockEvent())

            mock_repo.upsert.assert_called_once()
            upserted_data = mock_repo.upsert.call_args[0][0]

            assert upserted_data["public_key"] == "cc" * 32
            assert upserted_data["name"] == "Charlie"
            assert upserted_data["on_radio"] is True
            assert upserted_data["last_seen"] == 1700000000

            mock_broadcast.assert_called_once()
            event_type, contact_data = mock_broadcast.call_args[0]
            assert event_type == "contact"
            assert contact_data["public_key"] == "cc" * 32

    @pytest.mark.asyncio
    async def test_returns_early_on_empty_public_key(self):
        """Handler exits without upserting when public_key is empty."""
        from app.event_handlers import on_new_contact

        with (
            patch("app.event_handlers.ContactRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
        ):
            mock_repo.upsert = AsyncMock()

            class MockEvent:
                payload = {"public_key": "", "adv_name": "Ghost"}

            await on_new_contact(MockEvent())

            mock_repo.upsert.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_on_missing_public_key(self):
        """Handler exits without upserting when public_key field is absent."""
        from app.event_handlers import on_new_contact

        with (
            patch("app.event_handlers.ContactRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event") as mock_broadcast,
        ):
            mock_repo.upsert = AsyncMock()

            class MockEvent:
                payload = {"adv_name": "NoKey"}

            await on_new_contact(MockEvent())

            mock_repo.upsert.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_on_radio_true(self):
        """Contact data passed to upsert has on_radio=True."""
        from app.event_handlers import on_new_contact

        with (
            patch("app.event_handlers.ContactRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event"),
            patch("app.event_handlers.time") as mock_time,
        ):
            mock_time.time.return_value = 1700000000
            mock_repo.upsert = AsyncMock()

            class MockEvent:
                payload = {
                    "public_key": "dd" * 32,
                    "adv_name": "Delta",
                    "type": 0,
                    "flags": 0,
                }

            await on_new_contact(MockEvent())

            upserted_data = mock_repo.upsert.call_args[0][0]
            assert upserted_data["on_radio"] is True

    @pytest.mark.asyncio
    async def test_sets_last_seen_to_current_timestamp(self):
        """Contact data includes last_seen set to current time."""
        from app.event_handlers import on_new_contact

        with (
            patch("app.event_handlers.ContactRepository") as mock_repo,
            patch("app.event_handlers.broadcast_event"),
            patch("app.event_handlers.time") as mock_time,
        ):
            mock_time.time.return_value = 1700099999
            mock_repo.upsert = AsyncMock()

            class MockEvent:
                payload = {
                    "public_key": "ee" * 32,
                    "adv_name": "Echo",
                    "type": 0,
                    "flags": 0,
                }

            await on_new_contact(MockEvent())

            upserted_data = mock_repo.upsert.call_args[0][0]
            assert upserted_data["last_seen"] == 1700099999
