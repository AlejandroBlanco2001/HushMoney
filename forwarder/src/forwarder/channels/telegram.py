from __future__ import annotations

import argparse
import json
import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict, cast

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from forwarder import hermes
from forwarder.channels.telegram_config import TelegramConfig, load
from forwarder.sanitizer import sanitize


log = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
COMMANDS = frozenset({'/start', '/help', '/status', '/new', '/stop'})


class Message(TypedDict):
    update_id: int
    message_id: int
    date: int
    text: str
    forwarded: bool


def _as_mapping(value: object) -> dict[str, object]:
    return cast('dict[str, object]', value) if isinstance(value, dict) else {}


def _build_message(update: object, chat_id: int) -> Message | None:
    data = _as_mapping(update)
    message_data = _as_mapping(data.get('message'))
    chat = _as_mapping(message_data.get('chat'))
    sender = _as_mapping(message_data.get('from'))
    if (
        type(chat.get('id')) is not int
        or chat.get('id') != chat_id
        or chat.get('type') != 'private'
        or type(sender.get('id')) is not int
        or sender.get('id') != chat_id
        or sender.get('is_bot') is not False
        or 'via_bot' in message_data
    ):
        return None
    update_id = data.get('update_id')
    message_id, date = message_data.get('message_id'), message_data.get('date')
    text = message_data.get('text')
    if (
        type(update_id) is not int
        or type(message_id) is not int
        or type(date) is not int
        or min(update_id, message_id, date) < 0
        or not isinstance(text, str)
        or not 0 < len(text) <= 4096
    ):
        return None
    return Message(
        update_id=update_id,
        message_id=message_id,
        date=date,
        text=text,
        forwarded=any(key.startswith('forward_') for key in message_data),
    )


def _build_command_update(message: Message, chat_id: int) -> dict[str, object]:
    # Rebuild the update so names, quoted messages and other raw metadata never reach Hermes.
    return {
        'update_id': message['update_id'],
        'message': {
            'message_id': message['message_id'],
            'date': message['date'],
            'chat': {'id': chat_id, 'type': 'private'},
            'from': {'id': chat_id, 'is_bot': False, 'first_name': 'User'},
            'text': message['text'],
            'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(message['text'])}],
        },
    }


async def route_update(update: object, cfg: TelegramConfig, client: httpx.AsyncClient) -> None:
    message = _build_message(update, cfg.chat_id)
    if message is None:
        return
    if not message['forwarded'] and message['text'] in COMMANDS:
        await _post_json(
            client,
            cfg.hermes_webhook_url,
            _build_command_update(message, cfg.chat_id),
            {'X-Telegram-Bot-Api-Secret-Token': cfg.webhook_secret},
        )
        return
    payload = sanitize(message['text'], channel='sms')
    if payload is None:
        log.info('pattern not matched, telegram message dropped')
        return
    try:
        await hermes.dispatch_async(payload, cfg.gateway_url, cfg.gateway_secret, client)
    except httpx.HTTPError:
        log.warning('telegram dispatch failed, message dropped')


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> None:
    try:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError:
        # Acknowledge failures to Telegram: no raw payload persistence or retry queue.
        log.warning('telegram dispatch failed, message dropped')
    else:
        log.info('telegram message dispatched to hermes')


def create_app(cfg: TelegramConfig, client: httpx.AsyncClient | None = None) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds, follow_redirects=False) as owned:
            app.state.client = client or owned
            yield

    async def receive(request: Request) -> Response:
        supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not secrets.compare_digest(supplied.encode(), cfg.webhook_secret.encode()):
            return Response(status_code=403)
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    return Response(status_code=413)
                body.extend(chunk)
            update: object = json.loads(body)
        except (ValueError, UnicodeError, RecursionError, ClientDisconnect):
            return Response(status_code=400)
        await route_update(update, cfg, cast('httpx.AsyncClient', request.app.state.client))
        return Response(status_code=200)

    return Starlette(routes=[Route('/telegram', receive, methods=['POST'])], lifespan=lifespan)


def main() -> None:
    parser = argparse.ArgumentParser(description='Sanitize Telegram notifications before Hermes')
    parser.add_argument('--config', type=Path, default=Path('config/hermes.yaml'))
    args = parser.parse_args()
    try:
        cfg = load(args.config)
    except ValueError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, access_log=False)


if __name__ == '__main__':
    main()
