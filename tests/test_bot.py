"""Tests for the bot execution module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.bot as bot_module
from app.bot import (
    BOT_MESSAGE_SPACING,
    _bot_semaphore,
    execute_bot_code,
    process_bot_response,
    run_bot_for_message,
)
from app.models import BotConfig


class TestExecuteBotCode:
    """Test bot code execution."""

    def test_valid_code_returning_string(self):
        """Bot code that returns a string works correctly."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return f"Hello, {sender_name}!"
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result == "Hello, Alice!"

    def test_valid_code_returning_none(self):
        """Bot code that returns None works correctly."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return None
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_empty_string_response_treated_as_none(self):
        """Bot returning empty/whitespace string is treated as None."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return "   "
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_code_with_syntax_error(self):
        """Bot code with syntax error returns None."""
        code = """
def bot(sender_name:
    return "broken"
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_code_without_bot_function(self):
        """Code that doesn't define 'bot' function returns None."""
        code = """
def my_function():
    return "hello"
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_bot_not_callable(self):
        """Code where 'bot' is not callable returns None."""
        code = """
bot = "I'm a string, not a function"
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_bot_function_raises_exception(self):
        """Bot function that raises exception returns None."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    raise ValueError("oops!")
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_bot_returns_non_string(self):
        """Bot function returning non-string returns None."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return 42
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_empty_code_returns_none(self):
        """Empty bot code returns None."""
        result = execute_bot_code(
            code="",
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_whitespace_only_code_returns_none(self):
        """Whitespace-only bot code returns None."""
        result = execute_bot_code(
            code="   \n\t  ",
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_bot_receives_all_parameters(self):
        """Bot function receives all expected parameters."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    # Verify all params are accessible
    parts = [
        f"name={sender_name}",
        f"key={sender_key}",
        f"msg={message_text}",
        f"dm={is_dm}",
        f"ch_key={channel_key}",
        f"ch_name={channel_name}",
        f"ts={sender_timestamp}",
        f"path={path}",
    ]
    return "|".join(parts)
"""
        result = execute_bot_code(
            code=code,
            sender_name="Bob",
            sender_key="def456",
            message_text="Test",
            is_dm=False,
            channel_key="AABBCCDD",
            channel_name="#test",
            sender_timestamp=12345,
            path="001122",
        )
        assert (
            result
            == "name=Bob|key=def456|msg=Test|dm=False|ch_key=AABBCCDD|ch_name=#test|ts=12345|path=001122"
        )

    def test_channel_message_with_none_sender_key(self):
        """Channel messages correctly pass None for sender_key."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    if sender_key is None and not is_dm:
        return "channel message detected"
    return "unexpected"
"""
        result = execute_bot_code(
            code=code,
            sender_name="Someone",
            sender_key=None,  # Channel messages don't have sender key
            message_text="Test",
            is_dm=False,
            channel_key="AABBCCDD",
            channel_name="#general",
            sender_timestamp=None,
            path=None,
        )
        assert result == "channel message detected"

    def test_bot_returns_list_of_strings(self):
        """Bot function returning list of strings works correctly."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return ["First message", "Second message", "Third message"]
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result == ["First message", "Second message", "Third message"]

    def test_bot_returns_empty_list(self):
        """Bot function returning empty list is treated as None."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return []
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None

    def test_bot_returns_list_with_empty_strings_filtered(self):
        """Bot function returning list filters out empty/whitespace strings."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return ["Valid", "", "  ", "Also valid", None, 42]
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        # Only valid non-empty strings should remain
        assert result == ["Valid", "Also valid"]

    def test_bot_returns_list_all_empty_treated_as_none(self):
        """Bot function returning list of all empty strings is treated as None."""
        code = """
def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, path):
    return ["", "   ", ""]
"""
        result = execute_bot_code(
            code=code,
            sender_name="Alice",
            sender_key="abc123",
            message_text="Hi",
            is_dm=True,
            channel_key=None,
            channel_name=None,
            sender_timestamp=None,
            path=None,
        )
        assert result is None


class TestRunBotForMessage:
    """Test the main bot entry point."""

    @pytest.fixture(autouse=True)
    def reset_semaphore(self):
        """Reset semaphore state between tests."""
        # Ensure semaphore is fully released
        while _bot_semaphore.locked():
            _bot_semaphore.release()
        yield

    @pytest.mark.asyncio
    async def test_skips_outgoing_messages(self):
        """Bot is not triggered for outgoing messages."""
        with patch("app.repository.AppSettingsRepository") as mock_repo:
            await run_bot_for_message(
                sender_name="Me",
                sender_key="abc123",
                message_text="Hello",
                is_dm=True,
                channel_key=None,
                is_outgoing=True,
            )

            # Should not even check settings
            mock_repo.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_enabled_bots(self):
        """Bot is not triggered when no bots are enabled."""
        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Bot 1", enabled=False, code="def bot(): pass")
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with patch("app.bot.execute_bot_code") as mock_exec:
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123",
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_bots_array_empty(self):
        """Bot is not triggered when bots array is empty."""
        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = []
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with patch("app.bot.execute_bot_code") as mock_exec:
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123",
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_bot_with_empty_code(self):
        """Bot with empty code is skipped even if enabled."""
        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Empty Bot", enabled=True, code=""),
                BotConfig(id="2", name="Whitespace Bot", enabled=True, code="   "),
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with patch("app.bot.execute_bot_code") as mock_exec:
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123",
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_rechecks_settings_after_sleep(self):
        """Settings are re-checked after 2 second sleep."""
        with patch("app.repository.AppSettingsRepository") as mock_repo:
            # First call: bot enabled
            # Second call (after sleep): bot disabled
            mock_settings_enabled = MagicMock()
            mock_settings_enabled.bots = [
                BotConfig(id="1", name="Bot 1", enabled=True, code="def bot(): return 'hi'")
            ]

            mock_settings_disabled = MagicMock()
            mock_settings_disabled.bots = [
                BotConfig(id="1", name="Bot 1", enabled=False, code="def bot(): return 'hi'")
            ]

            mock_repo.get = AsyncMock(side_effect=[mock_settings_enabled, mock_settings_disabled])

            with (
                patch("app.bot.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
                patch("app.bot.execute_bot_code") as mock_exec,
            ):
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123",
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                # Should have slept
                mock_sleep.assert_called_once_with(2)

                # Should NOT have executed bot (disabled after sleep)
                mock_exec.assert_not_called()


class TestMultipleBots:
    """Test multiple bots functionality."""

    @pytest.fixture(autouse=True)
    def reset_semaphore(self):
        """Reset semaphore state between tests."""
        while _bot_semaphore.locked():
            _bot_semaphore.release()
        yield

    @pytest.fixture(autouse=True)
    def reset_rate_limit_state(self):
        """Reset rate limiting state between tests."""
        bot_module._last_bot_send_time = 0.0
        yield
        bot_module._last_bot_send_time = 0.0

    @pytest.mark.asyncio
    async def test_multiple_bots_execute_serially(self):
        """Multiple enabled bots execute serially in order."""
        executed_bots = []

        def mock_execute(code, *args, **kwargs):
            # Extract bot identifier from the code
            if "Bot 1" in code:
                executed_bots.append("Bot 1")
                return "Response 1"
            elif "Bot 2" in code:
                executed_bots.append("Bot 2")
                return "Response 2"
            return None

        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Bot 1", enabled=True, code="# Bot 1\ndef bot(): pass"),
                BotConfig(id="2", name="Bot 2", enabled=True, code="# Bot 2\ndef bot(): pass"),
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with (
                patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
                patch("app.bot.execute_bot_code", side_effect=mock_execute),
                patch("app.bot.process_bot_response", new_callable=AsyncMock),
            ):
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123" + "0" * 58,
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                # Both bots should have executed in order
                assert executed_bots == ["Bot 1", "Bot 2"]

    @pytest.mark.asyncio
    async def test_disabled_bots_are_skipped(self):
        """Disabled bots in the array are skipped."""
        executed_bots = []

        def mock_execute(code, *args, **kwargs):
            if "Bot 1" in code:
                executed_bots.append("Bot 1")
            elif "Bot 2" in code:
                executed_bots.append("Bot 2")
            elif "Bot 3" in code:
                executed_bots.append("Bot 3")
            return None

        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Bot 1", enabled=True, code="# Bot 1\ndef bot(): pass"),
                BotConfig(id="2", name="Bot 2", enabled=False, code="# Bot 2\ndef bot(): pass"),
                BotConfig(id="3", name="Bot 3", enabled=True, code="# Bot 3\ndef bot(): pass"),
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with (
                patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
                patch("app.bot.execute_bot_code", side_effect=mock_execute),
            ):
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123" + "0" * 58,
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                # Only enabled bots should have executed
                assert executed_bots == ["Bot 1", "Bot 3"]

    @pytest.mark.asyncio
    async def test_error_in_one_bot_doesnt_stop_others(self):
        """Error in one bot doesn't prevent other bots from running."""
        executed_bots = []

        def mock_execute(code, *args, **kwargs):
            if "Bot 1" in code:
                executed_bots.append("Bot 1")
                raise ValueError("Bot 1 crashed!")
            elif "Bot 2" in code:
                executed_bots.append("Bot 2")
                return "Response 2"
            elif "Bot 3" in code:
                executed_bots.append("Bot 3")
                return "Response 3"
            return None

        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Bot 1", enabled=True, code="# Bot 1\ndef bot(): pass"),
                BotConfig(id="2", name="Bot 2", enabled=True, code="# Bot 2\ndef bot(): pass"),
                BotConfig(id="3", name="Bot 3", enabled=True, code="# Bot 3\ndef bot(): pass"),
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with (
                patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
                patch("app.bot.execute_bot_code", side_effect=mock_execute),
                patch("app.bot.process_bot_response", new_callable=AsyncMock) as mock_respond,
            ):
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123" + "0" * 58,
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                # All bots should have been attempted
                assert executed_bots == ["Bot 1", "Bot 2", "Bot 3"]

                # Responses from successful bots should have been sent
                assert mock_respond.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_in_one_bot_doesnt_stop_others(self):
        """Timeout in one bot doesn't prevent other bots from running."""
        executed_bots = []

        async def mock_wait_for(coro, timeout):
            result = await coro
            # Simulate timeout for Bot 2
            if len(executed_bots) == 2 and executed_bots[-1] == "Bot 2":
                raise asyncio.TimeoutError()
            return result

        def mock_execute(code, *args, **kwargs):
            if "Bot 1" in code:
                executed_bots.append("Bot 1")
                return "Response 1"
            elif "Bot 2" in code:
                executed_bots.append("Bot 2")
                return "Response 2"  # This will be "timed out"
            elif "Bot 3" in code:
                executed_bots.append("Bot 3")
                return "Response 3"
            return None

        with patch("app.repository.AppSettingsRepository") as mock_repo:
            mock_settings = MagicMock()
            mock_settings.bots = [
                BotConfig(id="1", name="Bot 1", enabled=True, code="# Bot 1\ndef bot(): pass"),
                BotConfig(id="2", name="Bot 2", enabled=True, code="# Bot 2\ndef bot(): pass"),
                BotConfig(id="3", name="Bot 3", enabled=True, code="# Bot 3\ndef bot(): pass"),
            ]
            mock_repo.get = AsyncMock(return_value=mock_settings)

            with (
                patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
                patch("app.bot.execute_bot_code", side_effect=mock_execute),
                patch("app.bot.asyncio.wait_for", side_effect=mock_wait_for),
                patch("app.bot.process_bot_response", new_callable=AsyncMock) as mock_respond,
            ):
                await run_bot_for_message(
                    sender_name="Alice",
                    sender_key="abc123" + "0" * 58,
                    message_text="Hello",
                    is_dm=True,
                    channel_key=None,
                )

                # All bots should have been attempted
                assert executed_bots == ["Bot 1", "Bot 2", "Bot 3"]

                # Only responses from non-timed-out bots (Bot 1 and Bot 3)
                assert mock_respond.call_count == 2


class TestBotCodeValidation:
    """Test bot code syntax validation on save."""

    def test_valid_code_passes(self):
        """Valid Python code passes validation."""
        from app.routers.settings import validate_bot_code

        # Should not raise
        validate_bot_code("def bot(): return 'hello'")

    def test_syntax_error_raises(self):
        """Syntax error in code raises HTTPException."""
        from fastapi import HTTPException

        from app.routers.settings import validate_bot_code

        with pytest.raises(HTTPException) as exc_info:
            validate_bot_code("def bot(:\n    return 'broken'")

        assert exc_info.value.status_code == 400
        assert "syntax error" in exc_info.value.detail.lower()

    def test_syntax_error_includes_bot_name(self):
        """Syntax error message includes bot name when provided."""
        from fastapi import HTTPException

        from app.routers.settings import validate_bot_code

        with pytest.raises(HTTPException) as exc_info:
            validate_bot_code("def bot(:\n    return 'broken'", bot_name="My Test Bot")

        assert exc_info.value.status_code == 400
        assert "My Test Bot" in exc_info.value.detail

    def test_empty_code_passes(self):
        """Empty code passes validation (disables bot)."""
        from app.routers.settings import validate_bot_code

        # Should not raise
        validate_bot_code("")
        validate_bot_code("   ")

    def test_validate_all_bots(self):
        """validate_all_bots validates all bots' code."""
        from fastapi import HTTPException

        from app.routers.settings import validate_all_bots

        # Valid bots should pass
        valid_bots = [
            BotConfig(id="1", name="Bot 1", enabled=True, code="def bot(): return 'hi'"),
            BotConfig(id="2", name="Bot 2", enabled=False, code="def bot(): return 'hello'"),
        ]
        validate_all_bots(valid_bots)  # Should not raise

        # Invalid code should raise with bot name
        invalid_bots = [
            BotConfig(id="1", name="Good Bot", enabled=True, code="def bot(): return 'hi'"),
            BotConfig(id="2", name="Bad Bot", enabled=True, code="def bot(:"),
        ]
        with pytest.raises(HTTPException) as exc_info:
            validate_all_bots(invalid_bots)

        assert "Bad Bot" in exc_info.value.detail


class TestBotMessageRateLimiting:
    """Test bot message rate limiting for repeater compatibility."""

    @pytest.fixture(autouse=True)
    def reset_rate_limit_state(self):
        """Reset rate limiting state between tests."""
        bot_module._last_bot_send_time = 0.0
        yield
        bot_module._last_bot_send_time = 0.0

    @pytest.mark.asyncio
    async def test_first_send_does_not_wait(self):
        """First bot send should not wait (no previous send)."""
        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("app.routers.messages.send_direct_message", new_callable=AsyncMock) as mock_send,
            patch("app.websocket.broadcast_event"),
        ):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            mock_send.return_value = mock_message

            await process_bot_response(
                response="Hello!",
                is_dm=True,
                sender_key="abc123def456" * 4,  # 64 chars
                channel_key=None,
            )

            # Should not have slept (first send, _last_bot_send_time was 0)
            mock_sleep.assert_not_called()
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_rapid_second_send_waits(self):
        """Second send within spacing window should wait."""
        # Previous send was at 100.0, current time is 100.5 (0.5 seconds later)
        # So we need to wait 1.5 more seconds to reach 2.0 second spacing
        bot_module._last_bot_send_time = 100.0

        with (
            patch("app.bot.time.monotonic", return_value=100.5),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("app.routers.messages.send_direct_message", new_callable=AsyncMock) as mock_send,
            patch("app.websocket.broadcast_event"),
        ):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            mock_send.return_value = mock_message

            await process_bot_response(
                response="Hello again!",
                is_dm=True,
                sender_key="abc123def456" * 4,
                channel_key=None,
            )

            # Should have waited 1.5 seconds (2.0 - 0.5 elapsed)
            mock_sleep.assert_called_once()
            wait_time = mock_sleep.call_args[0][0]
            assert abs(wait_time - 1.5) < 0.01

    @pytest.mark.asyncio
    async def test_send_after_spacing_does_not_wait(self):
        """Send after spacing window should not wait."""
        # Simulate a previous send 3 seconds ago (> BOT_MESSAGE_SPACING)
        bot_module._last_bot_send_time = 97.0

        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("app.routers.messages.send_direct_message", new_callable=AsyncMock) as mock_send,
            patch("app.websocket.broadcast_event"),
        ):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            mock_send.return_value = mock_message

            await process_bot_response(
                response="Hello!",
                is_dm=True,
                sender_key="abc123def456" * 4,
                channel_key=None,
            )

            # Should not have slept (3 seconds > 2 second spacing)
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_timestamp_updated_after_successful_send(self):
        """Last send timestamp should be updated after successful send."""
        with (
            patch("app.bot.time.monotonic", return_value=150.0),
            patch("app.routers.messages.send_direct_message", new_callable=AsyncMock) as mock_send,
            patch("app.websocket.broadcast_event"),
        ):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            mock_send.return_value = mock_message

            await process_bot_response(
                response="Hello!",
                is_dm=True,
                sender_key="abc123def456" * 4,
                channel_key=None,
            )

            assert bot_module._last_bot_send_time == 150.0

    @pytest.mark.asyncio
    async def test_timestamp_not_updated_on_failure(self):
        """Last send timestamp should NOT be updated if send fails."""
        from fastapi import HTTPException

        bot_module._last_bot_send_time = 50.0  # Previous timestamp

        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch(
                "app.routers.messages.send_direct_message",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=500, detail="Send failed"),
            ),
        ):
            await process_bot_response(
                response="Hello!",
                is_dm=True,
                sender_key="abc123def456" * 4,
                channel_key=None,
            )

            # Timestamp should remain unchanged
            assert bot_module._last_bot_send_time == 50.0

    @pytest.mark.asyncio
    async def test_timestamp_not_updated_on_no_destination(self):
        """Last send timestamp should NOT be updated if no destination."""
        bot_module._last_bot_send_time = 50.0

        with patch("app.bot.time.monotonic", return_value=100.0):
            await process_bot_response(
                response="Hello!",
                is_dm=False,  # Not a DM
                sender_key="",
                channel_key=None,  # No channel either
            )

            # Timestamp should remain unchanged
            assert bot_module._last_bot_send_time == 50.0

    @pytest.mark.asyncio
    async def test_concurrent_sends_are_serialized(self):
        """Multiple concurrent sends should be serialized by the lock."""
        send_order = []
        send_times = []

        async def mock_send(*args, **kwargs):
            send_order.append(len(send_order))
            send_times.append(bot_module.time.monotonic())
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            return mock_message

        # Use a real monotonic-like counter for this test
        time_counter = [100.0]

        def mock_monotonic():
            return time_counter[0]

        async def mock_sleep(duration):
            time_counter[0] += duration

        with (
            patch("app.bot.time.monotonic", side_effect=mock_monotonic),
            patch("app.bot.asyncio.sleep", side_effect=mock_sleep),
            patch("app.routers.messages.send_direct_message", side_effect=mock_send),
            patch("app.websocket.broadcast_event"),
        ):
            # Launch 3 concurrent sends
            await asyncio.gather(
                process_bot_response("Msg 1", True, "a" * 64, None),
                process_bot_response("Msg 2", True, "b" * 64, None),
                process_bot_response("Msg 3", True, "c" * 64, None),
            )

            # All 3 should have sent
            assert len(send_order) == 3

            # Each send should be at least BOT_MESSAGE_SPACING apart
            # First send at 100, second at 102, third at 104
            assert send_times[1] >= send_times[0] + BOT_MESSAGE_SPACING - 0.01
            assert send_times[2] >= send_times[1] + BOT_MESSAGE_SPACING - 0.01

    @pytest.mark.asyncio
    async def test_channel_message_rate_limited(self):
        """Channel message sends should also be rate limited."""
        bot_module._last_bot_send_time = 99.0  # 1 second ago

        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("app.routers.messages.send_channel_message", new_callable=AsyncMock) as mock_send,
            patch("app.websocket.broadcast_event"),
        ):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            mock_send.return_value = mock_message

            await process_bot_response(
                response="Channel hello!",
                is_dm=False,
                sender_key="",
                channel_key="AABBCCDD" * 4,
            )

            # Should have waited 1 second (2.0 - 1.0 elapsed)
            mock_sleep.assert_called_once()
            wait_time = mock_sleep.call_args[0][0]
            assert abs(wait_time - 1.0) < 0.01
            mock_send.assert_called_once()


class TestBotListResponses:
    """Test bot functionality for list responses."""

    @pytest.fixture(autouse=True)
    def reset_rate_limit_state(self):
        """Reset rate limiting state between tests."""
        bot_module._last_bot_send_time = 0.0
        yield
        bot_module._last_bot_send_time = 0.0

    @pytest.mark.asyncio
    async def test_list_response_sends_multiple_messages(self):
        """List response should send multiple messages in order."""
        sent_messages = []

        async def mock_send(request):
            sent_messages.append(request.text)
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            return mock_message

        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
            patch("app.routers.messages.send_direct_message", side_effect=mock_send),
            patch("app.websocket.broadcast_event"),
        ):
            await process_bot_response(
                response=["First", "Second", "Third"],
                is_dm=True,
                sender_key="a" * 64,
                channel_key=None,
            )

            assert sent_messages == ["First", "Second", "Third"]

    @pytest.mark.asyncio
    async def test_list_response_rate_limited_between_messages(self):
        """Each message in a list should be rate limited."""
        sleep_calls = []

        time_counter = [100.0]

        def mock_monotonic():
            return time_counter[0]

        async def mock_sleep(duration):
            sleep_calls.append(duration)
            time_counter[0] += duration

        async def mock_send(request):
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            return mock_message

        with (
            patch("app.bot.time.monotonic", side_effect=mock_monotonic),
            patch("app.bot.asyncio.sleep", side_effect=mock_sleep),
            patch("app.routers.messages.send_direct_message", side_effect=mock_send),
            patch("app.websocket.broadcast_event"),
        ):
            await process_bot_response(
                response=["First", "Second", "Third"],
                is_dm=True,
                sender_key="a" * 64,
                channel_key=None,
            )

            # Should have waited between messages (after first send)
            # First message: no wait, Second: wait 2s, Third: wait 2s
            assert len(sleep_calls) == 2
            assert all(abs(w - BOT_MESSAGE_SPACING) < 0.01 for w in sleep_calls)

    @pytest.mark.asyncio
    async def test_string_response_still_works(self):
        """Single string response should still work after list support added."""
        sent_messages = []

        async def mock_send(request):
            sent_messages.append(request.text)
            mock_message = MagicMock()
            mock_message.model_dump.return_value = {}
            return mock_message

        with (
            patch("app.bot.time.monotonic", return_value=100.0),
            patch("app.bot.asyncio.sleep", new_callable=AsyncMock),
            patch("app.routers.messages.send_direct_message", side_effect=mock_send),
            patch("app.websocket.broadcast_event"),
        ):
            await process_bot_response(
                response="Just one message",
                is_dm=True,
                sender_key="a" * 64,
                channel_key=None,
            )

            assert sent_messages == ["Just one message"]
