"""Tests for configuration validation.

These tests verify transport mutual exclusivity, BLE PIN requirement,
and connection_type derivation.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestTransportExclusivity:
    """Ensure only one transport can be configured at a time."""

    def test_no_transport_defaults_to_serial(self):
        """No transport env vars means serial auto-detect."""
        s = Settings(serial_port="", tcp_host="", ble_address="")
        assert s.connection_type == "serial"

    def test_serial_only(self):
        s = Settings(serial_port="/dev/ttyUSB0")
        assert s.connection_type == "serial"

    def test_tcp_only(self):
        s = Settings(tcp_host="192.168.1.1")
        assert s.connection_type == "tcp"

    def test_tcp_with_custom_port(self):
        s = Settings(tcp_host="192.168.1.1", tcp_port=5000)
        assert s.connection_type == "tcp"
        assert s.tcp_port == 5000

    def test_tcp_default_port(self):
        s = Settings(tcp_host="192.168.1.1")
        assert s.tcp_port == 4000

    def test_ble_only(self):
        s = Settings(ble_address="AA:BB:CC:DD:EE:FF", ble_pin="123456")
        assert s.connection_type == "ble"

    def test_serial_and_tcp_rejected(self):
        with pytest.raises(ValidationError, match="Only one transport"):
            Settings(serial_port="/dev/ttyUSB0", tcp_host="192.168.1.1")

    def test_serial_and_ble_rejected(self):
        with pytest.raises(ValidationError, match="Only one transport"):
            Settings(
                serial_port="/dev/ttyUSB0",
                ble_address="AA:BB:CC:DD:EE:FF",
                ble_pin="123456",
            )

    def test_tcp_and_ble_rejected(self):
        with pytest.raises(ValidationError, match="Only one transport"):
            Settings(
                tcp_host="192.168.1.1",
                ble_address="AA:BB:CC:DD:EE:FF",
                ble_pin="123456",
            )

    def test_all_three_rejected(self):
        with pytest.raises(ValidationError, match="Only one transport"):
            Settings(
                serial_port="/dev/ttyUSB0",
                tcp_host="192.168.1.1",
                ble_address="AA:BB:CC:DD:EE:FF",
                ble_pin="123456",
            )


class TestBLEPinRequirement:
    """BLE address requires a PIN."""

    def test_ble_address_without_pin_rejected(self):
        with pytest.raises(ValidationError, match="MESHCORE_BLE_PIN is required"):
            Settings(ble_address="AA:BB:CC:DD:EE:FF", ble_pin="")

    def test_ble_address_with_pin_accepted(self):
        s = Settings(ble_address="AA:BB:CC:DD:EE:FF", ble_pin="123456")
        assert s.ble_address == "AA:BB:CC:DD:EE:FF"
        assert s.ble_pin == "123456"
