from __future__ import annotations

import logging

import httpx

from forwarder.sanitizer import CleanPayload


log = logging.getLogger(__name__)


def _headers(gateway_secret: str) -> dict[str, str]:
    headers = {'Content-Type': 'application/json'}
    if gateway_secret:
        headers['Authorization'] = f'Bearer {gateway_secret}'
    return headers


def dispatch(payload: CleanPayload, gateway_url: str, gateway_secret: str) -> None:
    resp = httpx.post(
        gateway_url, json=payload.to_json(), headers=_headers(gateway_secret), timeout=15
    )
    resp.raise_for_status()
    log.info('dispatched to hermes')


async def dispatch_async(
    payload: CleanPayload,
    gateway_url: str,
    gateway_secret: str,
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        gateway_url, json=payload.to_json(), headers=_headers(gateway_secret)
    )
    response.raise_for_status()
    log.info('dispatched to hermes')
