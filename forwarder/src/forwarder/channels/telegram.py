from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlsplit

import httpx
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from forwarder import hermes
from forwarder.sanitizer import SanitizeStatus, sanitize, sanitize_push


log = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
COMMANDS = frozenset({'/start', '/help', '/status', '/new', '/stop'})

_PUSH_RE = re.compile(r'^([A-Za-z]\S*):\s*(.+)', re.DOTALL)


@dataclass(frozen=True)
class TelegramConfig:
    chat_id: int
    webhook_secret: str = field(repr=False)
    gateway_secret: str = field(repr=False)
    gateway_url: str
    hermes_webhook_url: str
    host: str
    port: int
    timeout_seconds: float


def _get_required_secret(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'{name} is required')
    return value


def _load_settings(path: Path) -> dict[str, object]:
    try:
        document: object = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        raise ValueError('Cannot read Telegram configuration') from None
    for key in ('forwarder', 'telegram'):
        if not isinstance(document, dict):
            raise ValueError('Missing forwarder.telegram configuration')
        document = cast('dict[str, object]', document).get(key)
    if not isinstance(document, dict):
        raise ValueError('Missing forwarder.telegram configuration')
    return cast('dict[str, object]', document)


def _build_text(settings: dict[str, object], key: str) -> str:
    value = settings.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'forwarder.telegram.{key} must be a nonempty string')
    return value.strip()


def _build_url(settings: dict[str, object], key: str) -> str:
    value = _build_text(settings, key)
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in ('http', 'https')
            and parsed.hostname
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        raise ValueError(f'forwarder.telegram.{key} must be a valid HTTP URL') from None
    if not valid:
        raise ValueError(f'forwarder.telegram.{key} must be an HTTP URL without credentials')
    return value


def load(path: Path) -> TelegramConfig:
    settings = _load_settings(path)
    chat_id = _get_required_secret('TELEGRAM_CHAT_ID')
    if not re.fullmatch(r'[1-9][0-9]*', chat_id):
        raise ValueError('TELEGRAM_CHAT_ID must be a positive private chat ID')
    secret = _get_required_secret('TELEGRAM_WEBHOOK_SECRET')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', secret):
        raise ValueError('TELEGRAM_WEBHOOK_SECRET must use Telegram secret-token characters')
    port = settings.get('port')
    timeout = settings.get('timeout_seconds')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('forwarder.telegram.port must be between 1 and 65535')
    if type(timeout) not in (int, float) or not 0 < cast('float', timeout) <= 60:
        raise ValueError('forwarder.telegram.timeout_seconds must be between 0 and 60')
    return TelegramConfig(
        chat_id=int(chat_id),
        webhook_secret=secret,
        gateway_secret=os.environ.get('HERMES_GATEWAY_SECRET', '').strip(),
        gateway_url=_build_url(settings, 'gateway_url'),
        hermes_webhook_url=_build_url(settings, 'hermes_webhook_url'),
        host=_build_text(settings, 'host'),
        port=port,
        timeout_seconds=float(cast('float', timeout)),
    )


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


async def route_update(
    update: object,
    cfg: TelegramConfig,
    client: httpx.AsyncClient,
    unmatched_handler: object = None,
) -> None:
    from forwarder.learning.notification_filter import is_financial_notification
    from forwarder.sanitizer.registry import REGISTRY

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

    # Determine if this looks like a bank notification at all.
    snap = REGISTRY.snapshot()
    if not is_financial_notification(message['text'], snap.banks):
        log.info('telegram message is not a financial notification, dropped')
        return

    # Try push notification format first (App: body)
    push_match = _PUSH_RE.match(message['text'])
    if push_match:
        app_name, body = push_match.group(1), push_match.group(2)
        push_payload, bank_found = sanitize_push(app_name, body, channel='sms')
        if bank_found:
            if push_payload is not None:
                try:
                    await hermes.dispatch_async(
                        push_payload, cfg.gateway_url, cfg.gateway_secret, client
                    )
                except httpx.HTTPError:
                    log.warning('telegram push dispatch failed, message dropped')
                return
            # Known bank app but unmatched template
            result = sanitize(message['text'], channel='sms')
        else:
            result = sanitize(message['text'], channel='sms')
    else:
        result = sanitize(message['text'], channel='sms')

    if result.status == SanitizeStatus.MATCHED and result.payload is not None:
        try:
            await hermes.dispatch_async(result.payload, cfg.gateway_url, cfg.gateway_secret, client)
        except httpx.HTTPError:
            log.warning('telegram dispatch failed, message dropped')
        return

    # Unmatched — route to learning
    if unmatched_handler is not None:
        from forwarder.learning.unmatched import UnmatchedHandler

        assert isinstance(unmatched_handler, UnmatchedHandler)
        await unmatched_handler.handle_async(
            redacted_text=result.redacted_text,
            bank_slug=result.bank_slug,
            channel='sms',
            status=result.status,
            client=client,
        )
    else:
        log.info('telegram unmatched (no unmatched handler): %s', result.status)


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
        log.warning('telegram dispatch failed, message dropped')
    else:
        log.info('telegram message dispatched to hermes')


def create_app(
    cfg: TelegramConfig,
    client: httpx.AsyncClient | None = None,
    unmatched_handler: object = None,
) -> Starlette:
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
        await route_update(
            update,
            cfg,
            cast('httpx.AsyncClient', request.app.state.client),
            unmatched_handler,
        )
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
