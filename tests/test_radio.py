"""Tests for RadioManager multi-transport connect dispatch.

These tests verify that connect() routes to the correct transport method
based on settings.connection_type, and that connection_info is set correctly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRadioManagerConnect:
    """Test that connect() dispatches to the correct transport."""

    @pytest.mark.asyncio
    async def test_connect_serial_explicit_port(self):
        """Serial connect with explicit port sets connection_info."""
        from app.radio import RadioManager

        mock_mc = MagicMock()
        mock_mc.is_connected = True

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.MeshCore") as mock_meshcore,
        ):
            mock_settings.connection_type = "serial"
            mock_settings.serial_port = "/dev/ttyUSB0"
            mock_settings.serial_baudrate = 115200
            mock_meshcore.create_serial = AsyncMock(return_value=mock_mc)

            rm = RadioManager()
            await rm.connect()

            mock_meshcore.create_serial.assert_awaited_once_with(
                port="/dev/ttyUSB0",
                baudrate=115200,
                auto_reconnect=True,
                max_reconnect_attempts=10,
            )
            assert rm.connection_info == "Serial: /dev/ttyUSB0"
            assert rm.meshcore is mock_mc

    @pytest.mark.asyncio
    async def test_connect_serial_autodetect(self):
        """Serial connect without port auto-detects."""
        from app.radio import RadioManager

        mock_mc = MagicMock()
        mock_mc.is_connected = True

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.MeshCore") as mock_meshcore,
            patch("app.radio.find_radio_port", new_callable=AsyncMock) as mock_find,
        ):
            mock_settings.connection_type = "serial"
            mock_settings.serial_port = ""
            mock_settings.serial_baudrate = 115200
            mock_find.return_value = "/dev/ttyACM0"
            mock_meshcore.create_serial = AsyncMock(return_value=mock_mc)

            rm = RadioManager()
            await rm.connect()

            mock_find.assert_awaited_once_with(115200)
            assert rm.connection_info == "Serial: /dev/ttyACM0"

    @pytest.mark.asyncio
    async def test_connect_serial_autodetect_fails(self):
        """Serial auto-detect raises when no radio found."""
        from app.radio import RadioManager

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.find_radio_port", new_callable=AsyncMock) as mock_find,
        ):
            mock_settings.connection_type = "serial"
            mock_settings.serial_port = ""
            mock_settings.serial_baudrate = 115200
            mock_find.return_value = None

            rm = RadioManager()
            with pytest.raises(RuntimeError, match="No MeshCore radio found"):
                await rm.connect()

    @pytest.mark.asyncio
    async def test_connect_tcp(self):
        """TCP connect sets connection_info with host:port."""
        from app.radio import RadioManager

        mock_mc = MagicMock()
        mock_mc.is_connected = True

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.MeshCore") as mock_meshcore,
        ):
            mock_settings.connection_type = "tcp"
            mock_settings.tcp_host = "192.168.1.100"
            mock_settings.tcp_port = 4000
            mock_meshcore.create_tcp = AsyncMock(return_value=mock_mc)

            rm = RadioManager()
            await rm.connect()

            mock_meshcore.create_tcp.assert_awaited_once_with(
                host="192.168.1.100",
                port=4000,
                auto_reconnect=True,
                max_reconnect_attempts=10,
            )
            assert rm.connection_info == "TCP: 192.168.1.100:4000"
            assert rm.meshcore is mock_mc

    @pytest.mark.asyncio
    async def test_connect_ble(self):
        """BLE connect sets connection_info with address."""
        from app.radio import RadioManager

        mock_mc = MagicMock()
        mock_mc.is_connected = True

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.MeshCore") as mock_meshcore,
        ):
            mock_settings.connection_type = "ble"
            mock_settings.ble_address = "AA:BB:CC:DD:EE:FF"
            mock_settings.ble_pin = "123456"
            mock_meshcore.create_ble = AsyncMock(return_value=mock_mc)

            rm = RadioManager()
            await rm.connect()

            mock_meshcore.create_ble.assert_awaited_once_with(
                address="AA:BB:CC:DD:EE:FF",
                pin="123456",
                auto_reconnect=True,
                max_reconnect_attempts=15,
            )
            assert rm.connection_info == "BLE: AA:BB:CC:DD:EE:FF"
            assert rm.meshcore is mock_mc

    @pytest.mark.asyncio
    async def test_connect_disconnects_existing_first(self):
        """Calling connect() when already connected disconnects first."""
        from app.radio import RadioManager

        old_mc = MagicMock()
        old_mc.disconnect = AsyncMock()
        new_mc = MagicMock()
        new_mc.is_connected = True

        with (
            patch("app.radio.settings") as mock_settings,
            patch("app.radio.MeshCore") as mock_meshcore,
        ):
            mock_settings.connection_type = "tcp"
            mock_settings.tcp_host = "10.0.0.1"
            mock_settings.tcp_port = 4000
            mock_meshcore.create_tcp = AsyncMock(return_value=new_mc)

            rm = RadioManager()
            rm._meshcore = old_mc

            await rm.connect()

            old_mc.disconnect.assert_awaited_once()
            assert rm.meshcore is new_mc
