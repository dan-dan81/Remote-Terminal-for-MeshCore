"""Tests for the contacts router.

Verifies the contact CRUD endpoints, sync, mark-read, delete,
and add/remove from radio operations.

Uses FastAPI TestClient with mocked dependencies, consistent
with the test_api.py pattern.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from meshcore import EventType

# Sample 64-char hex public keys for testing
KEY_A = "aa" * 32  # aaaa...aa
KEY_B = "bb" * 32  # bbbb...bb
KEY_C = "cc" * 32  # cccc...cc


def _make_contact(public_key=KEY_A, name="Alice", **overrides):
    """Create a mock Contact model instance."""
    from app.models import Contact

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
        "on_radio": False,
        "last_contacted": None,
        "last_read_at": None,
    }
    defaults.update(overrides)
    return Contact(**defaults)


class TestListContacts:
    """Test GET /api/contacts."""

    def test_list_returns_contacts(self):
        from fastapi.testclient import TestClient

        contacts = [_make_contact(KEY_A, "Alice"), _make_contact(KEY_B, "Bob")]

        with patch(
            "app.routers.contacts.ContactRepository.get_all",
            new_callable=AsyncMock,
            return_value=contacts,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.get("/api/contacts")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["public_key"] == KEY_A
        assert data[1]["public_key"] == KEY_B

    def test_list_pagination_params(self):
        """Pagination parameters are forwarded to repository."""
        from fastapi.testclient import TestClient

        with patch(
            "app.routers.contacts.ContactRepository.get_all",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get_all:
            from app.main import app

            client = TestClient(app)
            response = client.get("/api/contacts?limit=5&offset=10")

        assert response.status_code == 200
        mock_get_all.assert_called_once_with(limit=5, offset=10)


class TestCreateContact:
    """Test POST /api/contacts."""

    def test_create_new_contact(self):
        from fastapi.testclient import TestClient

        with (
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.routers.contacts.ContactRepository.upsert",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.post(
                "/api/contacts",
                json={"public_key": KEY_A, "name": "NewContact"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["public_key"] == KEY_A
        assert data["name"] == "NewContact"
        mock_upsert.assert_called_once()

    def test_create_invalid_hex(self):
        """Non-hex public key returns 400."""
        from fastapi.testclient import TestClient

        with patch(
            "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.post(
                "/api/contacts",
                json={"public_key": "zz" * 32, "name": "Bad"},
            )

        assert response.status_code == 400
        assert "hex" in response.json()["detail"].lower()

    def test_create_short_key_rejected(self):
        """Key shorter than 64 chars is rejected by pydantic validation."""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/contacts",
            json={"public_key": "aa" * 16, "name": "Short"},
        )

        assert response.status_code == 422

    def test_create_existing_updates_name(self):
        """Creating a contact that exists updates the name."""
        from fastapi.testclient import TestClient

        existing = _make_contact(KEY_A, "OldName")

        with (
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.routers.contacts.ContactRepository.upsert",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.post(
                "/api/contacts",
                json={"public_key": KEY_A, "name": "NewName"},
            )

        assert response.status_code == 200
        # Upsert called with new name
        mock_upsert.assert_called_once()
        upsert_data = mock_upsert.call_args[0][0]
        assert upsert_data["name"] == "NewName"


class TestGetContact:
    """Test GET /api/contacts/{public_key}."""

    def test_get_existing(self):
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A, "Alice")

        with patch(
            "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
            new_callable=AsyncMock,
            return_value=contact,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.get(f"/api/contacts/{KEY_A}")

        assert response.status_code == 200
        assert response.json()["name"] == "Alice"

    def test_get_not_found(self):
        from fastapi.testclient import TestClient

        with patch(
            "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.get(f"/api/contacts/{KEY_A}")

        assert response.status_code == 404


class TestMarkRead:
    """Test POST /api/contacts/{public_key}/mark-read."""

    def test_mark_read_updates_timestamp(self):
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A)

        with (
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
            patch(
                "app.routers.contacts.ContactRepository.update_last_read_at",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/mark-read")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_mark_read_not_found(self):
        from fastapi.testclient import TestClient

        with patch(
            "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/mark-read")

        assert response.status_code == 404


class TestDeleteContact:
    """Test DELETE /api/contacts/{public_key}."""

    def test_delete_existing(self):
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A)

        with (
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
            patch(
                "app.routers.contacts.ContactRepository.delete",
                new_callable=AsyncMock,
            ),
            patch("app.routers.contacts.radio_manager") as mock_rm,
        ):
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            from app.main import app

            client = TestClient(app)
            response = client.delete(f"/api/contacts/{KEY_A}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_delete_not_found(self):
        from fastapi.testclient import TestClient

        with patch(
            "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from app.main import app

            client = TestClient(app)
            response = client.delete(f"/api/contacts/{KEY_A}")

        assert response.status_code == 404

    def test_delete_removes_from_radio_if_connected(self):
        """When radio is connected and contact is on radio, remove it first."""
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A, on_radio=True)
        mock_radio_contact = MagicMock()

        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=mock_radio_contact)
        mock_mc.commands.remove_contact = AsyncMock()

        with (
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
            patch(
                "app.routers.contacts.ContactRepository.delete",
                new_callable=AsyncMock,
            ),
            patch("app.routers.contacts.radio_manager") as mock_rm,
        ):
            mock_rm.is_connected = True
            mock_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.delete(f"/api/contacts/{KEY_A}")

        assert response.status_code == 200
        mock_mc.commands.remove_contact.assert_called_once_with(mock_radio_contact)


class TestSyncContacts:
    """Test POST /api/contacts/sync."""

    def test_sync_from_radio(self):
        from fastapi.testclient import TestClient

        mock_mc = MagicMock()
        mock_result = MagicMock()
        mock_result.type = EventType.OK
        mock_result.payload = {
            KEY_A: {"adv_name": "Alice", "type": 1, "flags": 0},
            KEY_B: {"adv_name": "Bob", "type": 1, "flags": 0},
        }
        mock_mc.commands.get_contacts = AsyncMock(return_value=mock_result)

        with (
            patch("app.dependencies.radio_manager") as mock_dep_rm,
            patch(
                "app.routers.contacts.ContactRepository.upsert", new_callable=AsyncMock
            ) as mock_upsert,
        ):
            mock_dep_rm.is_connected = True
            mock_dep_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.post("/api/contacts/sync")

        assert response.status_code == 200
        assert response.json()["synced"] == 2
        assert mock_upsert.call_count == 2

    def test_sync_requires_connection(self):
        from fastapi.testclient import TestClient

        with patch("app.dependencies.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            from app.main import app

            client = TestClient(app)
            response = client.post("/api/contacts/sync")

        assert response.status_code == 503


class TestAddRemoveRadio:
    """Test add-to-radio and remove-from-radio endpoints."""

    def test_add_to_radio(self):
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A)
        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=None)  # Not on radio
        mock_result = MagicMock()
        mock_result.type = EventType.OK
        mock_mc.commands.add_contact = AsyncMock(return_value=mock_result)

        with (
            patch("app.dependencies.radio_manager") as mock_dep_rm,
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
            patch(
                "app.routers.contacts.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ) as mock_set_on_radio,
        ):
            mock_dep_rm.is_connected = True
            mock_dep_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/add-to-radio")

        assert response.status_code == 200
        mock_mc.commands.add_contact.assert_called_once()
        mock_set_on_radio.assert_called_once_with(KEY_A, True)

    def test_add_already_on_radio(self):
        """Adding a contact already on radio returns ok without calling add_contact."""
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A, on_radio=True)
        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=MagicMock())  # On radio

        with (
            patch("app.dependencies.radio_manager") as mock_dep_rm,
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
        ):
            mock_dep_rm.is_connected = True
            mock_dep_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/add-to-radio")

        assert response.status_code == 200
        assert "already" in response.json()["message"].lower()

    def test_remove_from_radio(self):
        from fastapi.testclient import TestClient

        contact = _make_contact(KEY_A, on_radio=True)
        mock_radio_contact = MagicMock()
        mock_mc = MagicMock()
        mock_mc.get_contact_by_key_prefix = MagicMock(return_value=mock_radio_contact)
        mock_result = MagicMock()
        mock_result.type = EventType.OK
        mock_mc.commands.remove_contact = AsyncMock(return_value=mock_result)

        with (
            patch("app.dependencies.radio_manager") as mock_dep_rm,
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=contact,
            ),
            patch(
                "app.routers.contacts.ContactRepository.set_on_radio",
                new_callable=AsyncMock,
            ) as mock_set_on_radio,
        ):
            mock_dep_rm.is_connected = True
            mock_dep_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/remove-from-radio")

        assert response.status_code == 200
        mock_mc.commands.remove_contact.assert_called_once_with(mock_radio_contact)
        mock_set_on_radio.assert_called_once_with(KEY_A, False)

    def test_add_requires_connection(self):
        from fastapi.testclient import TestClient

        with patch("app.dependencies.radio_manager") as mock_rm:
            mock_rm.is_connected = False
            mock_rm.meshcore = None

            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/add-to-radio")

        assert response.status_code == 503

    def test_remove_not_found(self):
        from fastapi.testclient import TestClient

        mock_mc = MagicMock()

        with (
            patch("app.dependencies.radio_manager") as mock_dep_rm,
            patch(
                "app.routers.contacts.ContactRepository.get_by_key_or_prefix",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_dep_rm.is_connected = True
            mock_dep_rm.meshcore = mock_mc

            from app.main import app

            client = TestClient(app)
            response = client.post(f"/api/contacts/{KEY_A}/remove-from-radio")

        assert response.status_code == 404
