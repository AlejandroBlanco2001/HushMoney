from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MY_ID = 111
BOT_USERNAME = "@testbot"
ENV = {
    "TELEGRAM_API_ID": "1",
    "TELEGRAM_API_HASH": "abc",
    "BOT_USERNAME": BOT_USERNAME,
    "TELEGRAM_CHAT_ID": str(MY_ID),
    "TELEGRAM_SESSION_STRING": "fake",
}


def _make_msg(chat_id: int, text: str | None) -> MagicMock:
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    return msg


@pytest.fixture()
def handler():
    """Import on_message after stubbing pyrogram and the environment."""
    pyrogram_stub = types.ModuleType("pyrogram")
    pyrogram_stub.Client = MagicMock()
    pyrogram_stub.idle = AsyncMock()
    pyrogram_stub.filters = MagicMock()

    filters_stub = types.ModuleType("pyrogram.filters")
    types_stub = types.ModuleType("pyrogram.types")
    types_stub.Message = MagicMock()

    stubs = {
        "pyrogram": pyrogram_stub,
        "pyrogram.filters": filters_stub,
        "pyrogram.types": types_stub,
    }

    with patch.dict(sys.modules, stubs), patch.dict("os.environ", ENV, clear=False):
        # Remove cached module so it re-imports cleanly with our stubs.
        sys.modules.pop("scripts.sms_listener", None)
        import importlib.util, pathlib

        spec = importlib.util.spec_from_file_location(
            "sms_listener",
            pathlib.Path(__file__).parents[2] / "scripts" / "sms_listener.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        yield mod.handle


@pytest.mark.asyncio
async def test_saved_messages_text_is_forwarded(handler):
    client = AsyncMock()
    msg = _make_msg(MY_ID, "Bancolombia: Transferiste $75.000,00 desde tu cuenta")
    await handler(client, msg)
    client.send_message.assert_awaited_once_with(BOT_USERNAME, msg.text)


@pytest.mark.asyncio
async def test_wrong_chat_is_ignored(handler):
    client = AsyncMock()
    msg = _make_msg(999, "Bancolombia: Transferiste $75.000,00 desde tu cuenta")
    await handler(client, msg)
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_without_text_is_ignored(handler):
    client = AsyncMock()
    msg = _make_msg(MY_ID, None)
    await handler(client, msg)
    client.send_message.assert_not_awaited()
