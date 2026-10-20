from __future__ import annotations

import logging

import httpx

from forwarder.imap import Email


log = logging.getLogger(__name__)


def dispatch(e: Email, gateway_url: str, gateway_secret: str) -> None:
    headers = {'Content-Type': 'application/json'}
    if gateway_secret:
        headers['Authorization'] = f'Bearer {gateway_secret}'

    payload = {
        'channel': 'email',
        'from': e.from_,
        'subject': e.subject,
        'body': e.body,
    }

    resp = httpx.post(gateway_url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    log.info('dispatched to hermes from=%s subject=%r', e.from_, e.subject)
