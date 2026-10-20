from __future__ import annotations

import logging

import httpx

from forwarder.sanitizer import CleanPayload


log = logging.getLogger(__name__)


def dispatch(payload: CleanPayload, gateway_url: str, gateway_secret: str) -> None:
    headers = {'Content-Type': 'application/json'}
    if gateway_secret:
        headers['Authorization'] = f'Bearer {gateway_secret}'

    resp = httpx.post(gateway_url, json=payload.to_json(), headers=headers, timeout=15)
    resp.raise_for_status()
    log.info('dispatched to hermes')


async def dispatch_async(
    payload: CleanPayload,
    gateway_url: str,
    gateway_secret: str,
    client: httpx.AsyncClient,
) -> None:
    headers = {'Authorization': f'Bearer {gateway_secret}'} if gateway_secret else {}
    response = await client.post(gateway_url, json=payload.to_json(), headers=headers)
    response.raise_for_status()
    log.info('dispatched to hermes')
