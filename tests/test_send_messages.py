"""Tests for bot triggering on outgoing messages sent via the messages router."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from meshcore import EventType

from app.models import Channel, Contact, SendChannelMessageRequest, SendDirectMessageRequest
from app.routers.messages import send_channel_message, send_direct_message


def _make_radio_result(payload=None):
    """Create a mock radio command result."""
    result = MagicMock()
    result.type = EventType.MSG_SENT
    result.payload = payload or {}
    return result


def _make_mc(name="TestNode"):
    """Create a mock MeshCore connection."""
    mc = MagicMock()
    mc.self_info = {"name": name}
    mc.commands = MagicMock()
    mc.commands.send_msg = AsyncMock(return_value=_make_radio_result())
    mc.commands.send_chan_msg = AsyncMock(return_value=_make_radio_result())
    mc.commands.add_contact = AsyncMock(return_value=_make_radio_result())
    mc.commands.set_channel = AsyncMock(return_value=_make_radio_result())
    mc.get_contact_by_key_prefix = MagicMock(return_value=None)
    return mc


class TestOutgoingDMBotTrigger:
    """Test that sending a DM triggers bots with is_outgoing=True."""

    @pytest.mark.asyncio
    async def test_send_dm_triggers_bot(self):
        """Sending a DM creates a background task to run bots."""
        mc = _make_mc()
        db_contact = Contact(public_key="ab" * 32, name="Alice")

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ContactRepository.get_by_key_or_prefix",
                new=AsyncMock(return_value=db_contact),
            ),
            patch("app.repository.ContactRepository.update_last_contacted", new=AsyncMock()),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.bot.run_bot_for_message", new=AsyncMock()) as mock_bot,
        ):
            request = SendDirectMessageRequest(
                destination=db_contact.public_key, text="!lasttime Alice"
            )
            await send_direct_message(request)

            # Let the background task run
            await asyncio.sleep(0)

            mock_bot.assert_called_once()
            call_kwargs = mock_bot.call_args[1]
            assert call_kwargs["message_text"] == "!lasttime Alice"
            assert call_kwargs["is_dm"] is True
            assert call_kwargs["is_outgoing"] is True
            assert call_kwargs["sender_key"] == db_contact.public_key
            assert call_kwargs["channel_key"] is None

    @pytest.mark.asyncio
    async def test_send_dm_bot_does_not_block_response(self):
        """Bot trigger runs in background and doesn't delay the message response."""
        mc = _make_mc()
        db_contact = Contact(public_key="ab" * 32, name="Alice")

        # Bot that would take a long time
        async def _slow(**kw):
            await asyncio.sleep(10)

        slow_bot = AsyncMock(side_effect=_slow)

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ContactRepository.get_by_key_or_prefix",
                new=AsyncMock(return_value=db_contact),
            ),
            patch("app.repository.ContactRepository.update_last_contacted", new=AsyncMock()),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.bot.run_bot_for_message", new=slow_bot),
        ):
            request = SendDirectMessageRequest(destination=db_contact.public_key, text="Hello")
            # This should return immediately, not wait 10 seconds
            message = await send_direct_message(request)
            assert message.text == "Hello"
            assert message.outgoing is True

    @pytest.mark.asyncio
    async def test_send_dm_passes_no_sender_name(self):
        """Outgoing DMs pass sender_name=None (we are the sender)."""
        mc = _make_mc()
        db_contact = Contact(public_key="cd" * 32, name="Bob")

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ContactRepository.get_by_key_or_prefix",
                new=AsyncMock(return_value=db_contact),
            ),
            patch("app.repository.ContactRepository.update_last_contacted", new=AsyncMock()),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.bot.run_bot_for_message", new=AsyncMock()) as mock_bot,
        ):
            request = SendDirectMessageRequest(destination=db_contact.public_key, text="test")
            await send_direct_message(request)
            await asyncio.sleep(0)

            call_kwargs = mock_bot.call_args[1]
            assert call_kwargs["sender_name"] is None


class TestOutgoingChannelBotTrigger:
    """Test that sending a channel message triggers bots with is_outgoing=True."""

    @pytest.mark.asyncio
    async def test_send_channel_msg_triggers_bot(self):
        """Sending a channel message creates a background task to run bots."""
        mc = _make_mc(name="MyNode")
        db_channel = Channel(key="aa" * 16, name="#general")

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ChannelRepository.get_by_key",
                new=AsyncMock(return_value=db_channel),
            ),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.decoder.calculate_channel_hash", return_value="abcd"),
            patch("app.bot.run_bot_for_message", new=AsyncMock()) as mock_bot,
        ):
            request = SendChannelMessageRequest(
                channel_key=db_channel.key, text="!lasttime5 someone"
            )
            await send_channel_message(request)
            await asyncio.sleep(0)

            mock_bot.assert_called_once()
            call_kwargs = mock_bot.call_args[1]
            assert call_kwargs["message_text"] == "!lasttime5 someone"
            assert call_kwargs["is_dm"] is False
            assert call_kwargs["is_outgoing"] is True
            assert call_kwargs["channel_key"] == db_channel.key.upper()
            assert call_kwargs["channel_name"] == "#general"
            assert call_kwargs["sender_name"] == "MyNode"
            assert call_kwargs["sender_key"] is None

    @pytest.mark.asyncio
    async def test_send_channel_msg_no_radio_name(self):
        """When radio has no name, sender_name is None."""
        mc = _make_mc(name="")
        db_channel = Channel(key="bb" * 16, name="#test")

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ChannelRepository.get_by_key",
                new=AsyncMock(return_value=db_channel),
            ),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.decoder.calculate_channel_hash", return_value="abcd"),
            patch("app.bot.run_bot_for_message", new=AsyncMock()) as mock_bot,
        ):
            request = SendChannelMessageRequest(channel_key=db_channel.key, text="hello")
            await send_channel_message(request)
            await asyncio.sleep(0)

            call_kwargs = mock_bot.call_args[1]
            assert call_kwargs["sender_name"] is None

    @pytest.mark.asyncio
    async def test_send_channel_msg_bot_does_not_block_response(self):
        """Bot trigger runs in background and doesn't delay the message response."""
        mc = _make_mc(name="MyNode")
        db_channel = Channel(key="cc" * 16, name="#slow")

        async def _slow(**kw):
            await asyncio.sleep(10)

        slow_bot = AsyncMock(side_effect=_slow)

        with (
            patch("app.routers.messages.require_connected", return_value=mc),
            patch(
                "app.repository.ChannelRepository.get_by_key",
                new=AsyncMock(return_value=db_channel),
            ),
            patch("app.repository.MessageRepository.create", new=AsyncMock(return_value=1)),
            patch("app.decoder.calculate_channel_hash", return_value="abcd"),
            patch("app.bot.run_bot_for_message", new=slow_bot),
        ):
            request = SendChannelMessageRequest(channel_key=db_channel.key, text="test")
            message = await send_channel_message(request)
            assert message.outgoing is True
