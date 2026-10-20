"""
Tests an IMAP connection and reports how many unread emails exist from the
given bank sender addresses.

Usage:
  python3 check_imap.py --host HOST --port PORT --username USER
                        --password PASS --senders "a@b.com,c@d.com"

Output JSON:
  { "success": true, "unseen_from_bank": N }
  { "success": false, "error": "auth"|"connection"|"sender_not_found", "detail": "..." }
"""
from __future__ import annotations

import argparse
import imaplib
import json
import socket
import ssl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',     required=True)
    parser.add_argument('--port',     type=int, default=993)
    parser.add_argument('--username', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--senders',  default='')
    args = parser.parse_args()

    senders = [s.strip() for s in args.senders.split(',') if s.strip()]

    try:
        conn = imaplib.IMAP4_SSL(args.host, args.port)
    except (OSError, socket.gaierror, ssl.SSLError) as exc:
        print(json.dumps({'success': False, 'error': 'connection', 'detail': str(exc)}))
        return

    try:
        conn.login(args.username, args.password)
    except imaplib.IMAP4.error as exc:
        print(json.dumps({'success': False, 'error': 'auth', 'detail': str(exc)}))
        return

    conn.select('INBOX')

    unseen = 0
    for sender in senders:
        _, data = conn.search(None, 'UNSEEN', f'FROM "{sender}"')
        if data and data[0]:
            unseen += len(data[0].split())

    conn.logout()

    if senders and unseen == 0:
        print(json.dumps({'success': True, 'unseen_from_bank': 0,
                          'error': 'sender_not_found'}))
    else:
        print(json.dumps({'success': True, 'unseen_from_bank': unseen}))


if __name__ == '__main__':
    main()
