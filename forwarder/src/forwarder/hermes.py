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
