"""
Stateful setup wizard for HushMoney.

The LLM calls this script with the user's reply. It manages all state in
user_settings, outputs exactly one message per call, and never asks two
questions at once.

Usage:
  python3 setup_wizard.py                   # show current question (resume)
  python3 setup_wizard.py --answer TEXT     # process reply, advance state

Output JSON (always one object):
  {"step": "...", "message": "...", "done": false}
  {"step": "complete", "message": "...", "done": true}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
SCHEMA_PATH = os.environ.get('HUSHMONEY_SCHEMA', '/app/config/schema.sql')
_HERE = Path(__file__).parent
TEMPLATES = _HERE.parent / 'templates'

BANKS: list[tuple[str, str]] = [
    ('bancolombia', 'Bancolombia'),
    ('davivienda', 'Davivienda'),
    ('nequi', 'Nequi'),
    ('bbva', 'BBVA Colombia'),
]
ACCT_TYPES: list[tuple[str, str]] = [
    ('checking', 'Checking / Savings (cuenta de ahorros / corriente)'),
    ('credit', 'Credit card'),
    ('digital_wallet', 'Digital wallet (Nequi, Daviplata, etc.)'),
]
IMAP_PRESETS: dict[str, tuple[str, str]] = {
    'gmail': ('imap.gmail.com', '993'),
    'yahoo': ('imap.mail.yahoo.com', '993'),
}


# ── DB helpers ───────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if os.path.isfile(SCHEMA_PATH):
        con.executescript(Path(SCHEMA_PATH).read_text())
    return con


def _load(con: sqlite3.Connection) -> dict[str, str]:
    return {r['key']: r['value']
            for r in con.execute('SELECT key, value FROM user_settings').fetchall()}


def _save(con: sqlite3.Connection, **kwargs: str) -> None:
    now = datetime.now(UTC).isoformat()
    with con:
        for key, value in kwargs.items():
            con.execute(
                'INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)'
                ' ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (key, value, now),
            )


# ── Output ───────────────────────────────────────────────────────────────────

def _out(step: str, message: str, done: bool = False) -> None:
    sys.stdout.write(json.dumps({'step': step, 'message': message, 'done': done}) + '\n')
    sys.stdout.flush()


def _tmpl(name: str) -> str:
    p = TEMPLATES / name
    return p.read_text(encoding='utf-8').strip() if p.is_file() else ''


# ── Sub-process helpers ───────────────────────────────────────────────────────

def _run(script: str, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(_HERE / script), *args],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {'ok': False, 'error': result.stderr.strip()}


def _check_imap(host: str, port: str, username: str, password: str, senders: str = '') -> dict:
    return _run('check_imap.py',
                '--host', host, '--port', port,
                '--username', username, '--password', password,
                '--senders', senders)


def _save_email_config(provider: str, host: str, port: str, username: str, senders: str) -> None:
    _run('save_email_config.py',
         '--provider', provider, '--host', host, '--port', port,
         '--username', username, '--bank-senders', senders)


def _save_account(bank: str, acct_type: str, currency: str,
                  last4: str, card4: str, alias: str) -> None:
    args = ['--bank', bank, '--type', acct_type, '--currency', currency]
    if last4:
        args += ['--masked-number', f'****{last4}']
    if card4:
        args += ['--card-masked-number', f'****{card4}']
    if alias:
        args += ['--alias', alias]
    _run('save_accounts.py', *args)


def _mark_complete(con: sqlite3.Connection) -> None:
    _run('mark_setup_complete.py')
    _save(con, wizard_step='complete')


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _pick_nums(text: str, max_n: int) -> list[int]:
    """Return 0-based indices from a user selection like '1,3' or '1 2'."""
    found = [int(m) - 1 for m in re.findall(r'\d+', text)]
    return list(dict.fromkeys(i for i in found if 0 <= i < max_n))


def _is_skip(text: str) -> bool:
    return text.lower().strip() in ('skip', 'omit', 'no', 'none', '-', '.', '')


def _currency(text: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z]', '', text).upper()
    return cleaned if 2 <= len(cleaned) <= 4 else 'COP'


# ── Question strings ──────────────────────────────────────────────────────────

def _q_banks() -> str:
    lines = ['Which banks do you have accounts with? Reply with numbers separated by commas.\n']
    for i, (_, name) in enumerate(BANKS, 1):
        lines.append(f'{i}. {name}')
    lines.append('5. Other')
    return '\n'.join(lines)


def _q_types(bank_name: str) -> str:
    lines = [f'What types of accounts do you have with {bank_name}? Reply with numbers, comma-separated.\n']
    for i, (_, label) in enumerate(ACCT_TYPES, 1):
        lines.append(f'{i}. {label}')
    return '\n'.join(lines)


def _q_sms() -> str:
    return (
        'Would you also like to set up SMS forwarding? '
        'This lets me capture bank texts automatically.\n\n'
        '1. Yes — set it up now\n'
        '2. Skip — I\'ll do this later'
    )


# ── Account queue helpers ─────────────────────────────────────────────────────

def _start_next_account(con: sqlite3.Connection, queue: list[dict]) -> None:
    if not queue:
        _save(con, wizard_step='sms_choice')
        _out('sms_choice', _q_sms())
        return
    acct = queue.pop(0)
    bank_name = dict(BANKS).get(acct['bank'], acct['bank'].title())
    _save(con,
          wizard_step='account_last4',
          wizard_current_account=json.dumps(acct),
          wizard_accounts_queue=json.dumps(queue),
          wizard_cur_last4='', wizard_cur_card='', wizard_cur_currency='COP')
    _out('account_last4',
         f'What are the last 4 digits of the account number shown in {bank_name} notifications?\n'
         '(e.g. "Cta ****1234" → type 1234, or "skip" to leave blank)')


# ── Finalize ──────────────────────────────────────────────────────────────────

def _finalize(con: sqlite3.Connection, s: dict) -> None:
    _mark_complete(con)
    email_user = s.get('imap_username') or s.get('wizard_imap_username', '')
    senders = s.get('bank_sender_emails') or s.get('wizard_bank_senders', '')
    n_accts = con.execute('SELECT count(*) FROM accounts').fetchone()[0]
    reached_sms = s.get('wizard_step', '') not in ('sms_choice', 'welcome', 'welcome_choice')

    email_line = f'- **Email**: watching {email_user}' if email_user else '- **Email**: not configured'
    sms_line = '- **SMS**: configured ✅' if reached_sms else '- **SMS**: not configured'

    _out('complete',
         '🎉 Setup complete! Here\'s what\'s active:\n\n'
         f'{email_line}\n'
         f'- **Accounts**: {n_accts} account(s) registered\n'
         f'{sms_line}\n\n'
         'I\'ll notify you on Telegram when I capture a transaction. You can also ask me:\n'
         '- "How much did I spend this week?"\n'
         '- "Carlos owes me $35,000 from dinner"\n'
         '- "Show my monthly summary"',
         done=True)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--answer', default=None)
    args = parser.parse_args()
    ans = (args.answer or '').strip()

    con = _connect()
    s = _load(con)
    step = s.get('wizard_step', 'welcome')

    # Already done
    if step in ('complete', 'done') and s.get('setup_complete') == 'true':
        _out('complete', 'You\'re already set up! Send me a transaction or ask for a summary.', done=True)
        return

    # ── welcome ──────────────────────────────────────────────────────────────
    if step == 'welcome':
        preload = _run('load_accounts_md.py')
        _save(con,
              wizard_step='welcome_choice',
              wizard_accounts_preloaded='true' if preload.get('ready') else 'false')
        tmpl = _tmpl('welcome.md')
        body = (tmpl + '\n\n' if tmpl else '') + (
            'How would you like to get started?\n\n'
            '1. Full setup — configure email + accounts + SMS\n'
            '2. Accounts only — skip email, just register your accounts\n\n'
            'Reply 1 or 2.'
        )
        _out('welcome_choice', body)
        return

    # ── welcome_choice ────────────────────────────────────────────────────────
    if step == 'welcome_choice':
        if not ans:
            _out('welcome_choice',
                 'How would you like to get started?\n\n'
                 '1. Full setup — configure email + accounts + SMS\n'
                 '2. Accounts only — skip email, just register your accounts\n\n'
                 'Reply 1 or 2.')
            return
        mode = 'accounts_only' if ans.strip().startswith('2') else 'full'
        preloaded = s.get('wizard_accounts_preloaded') == 'true'
        _save(con, wizard_mode=mode)
        if mode == 'full':
            _save(con, wizard_step='email_provider')
            _out('email_provider',
                 'Which email provider receives your bank\'s notification emails?\n\n'
                 '1. Gmail\n2. Yahoo Mail\n3. Outlook / Microsoft 365\n4. Other')
        elif preloaded:
            _save(con, wizard_step='sms_choice')
            _out('sms_choice', _q_sms())
        else:
            _save(con, wizard_step='accounts_banks')
            _out('accounts_banks', _q_banks())
        return

    # ── email_provider ────────────────────────────────────────────────────────
    if step == 'email_provider':
        if not ans:
            _out('email_provider',
                 'Which email provider?\n\n1. Gmail\n2. Yahoo Mail\n3. Outlook / Microsoft 365\n4. Other')
            return
        low = ans.lower()
        if '1' in ans or 'gmail' in low or 'google' in low:
            host, port = IMAP_PRESETS['gmail']
            _save(con, wizard_step='email_address',
                  wizard_email_provider='gmail',
                  wizard_imap_host=host, wizard_imap_port=port)
            _out('email_address', _tmpl('email_gmail.md') + '\n\nWhat is your Gmail address?')
        elif '2' in ans or 'yahoo' in low:
            host, port = IMAP_PRESETS['yahoo']
            _save(con, wizard_step='email_address',
                  wizard_email_provider='yahoo',
                  wizard_imap_host=host, wizard_imap_port=port)
            _out('email_address', _tmpl('email_yahoo.md') + '\n\nWhat is your Yahoo email address?')
        elif '3' in ans or 'outlook' in low or 'microsoft' in low or 'hotmail' in low:
            _save(con, wizard_step='email_outlook_redirect',
                  wizard_email_provider='outlook_forward')
            tmpl = _tmpl('email_outlook.md')
            _out('email_outlook_redirect',
                 (tmpl + '\n\n' if tmpl else '') +
                 'Once the forwarding rule is active, which Gmail or Yahoo address will receive the forwarded emails?')
        else:
            _save(con, wizard_step='email_other_host', wizard_email_provider='other')
            _out('email_other_host', 'What is your IMAP server hostname? (e.g. imap.example.com)')
        return

    # ── email_outlook_redirect ────────────────────────────────────────────────
    if step == 'email_outlook_redirect':
        if not ans or '@' not in ans:
            _out('email_outlook_redirect',
                 'Which Gmail or Yahoo address will receive the forwarded bank emails?')
            return
        domain = ans.split('@')[-1].lower()
        if 'gmail' in domain:
            host, port = IMAP_PRESETS['gmail']
        elif 'yahoo' in domain or 'ymail' in domain:
            host, port = IMAP_PRESETS['yahoo']
        else:
            _out('email_outlook_redirect',
                 'I need a Gmail or Yahoo address for the forwarding target.\n'
                 'Which Gmail or Yahoo address should receive the forwarded emails?')
            return
        _save(con, wizard_step='email_password',
              wizard_imap_host=host, wizard_imap_port=port, wizard_imap_username=ans.strip())
        _out('email_password', 'Paste your App Password (16 characters, no spaces):')
        return

    # ── email_other_host ──────────────────────────────────────────────────────
    if step == 'email_other_host':
        if not ans:
            _out('email_other_host', 'What is your IMAP server hostname?')
            return
        _save(con, wizard_step='email_other_port', wizard_imap_host=ans)
        _out('email_other_port', 'What port does it use? (default 993 — type "993" to keep it)')
        return

    if step == 'email_other_port':
        port = re.search(r'\d+', ans)
        _save(con, wizard_step='email_address', wizard_imap_port=port.group() if port else '993')
        _out('email_address', 'What is your email address?')
        return

    # ── email_address ─────────────────────────────────────────────────────────
    if step == 'email_address':
        if not ans or '@' not in ans:
            _out('email_address', 'What is your email address?')
            return
        _save(con, wizard_step='email_password', wizard_imap_username=ans.strip())
        _out('email_password', 'Paste your App Password (16 characters, no spaces):')
        return

    # ── email_password ────────────────────────────────────────────────────────
    if step == 'email_password':
        if not ans:
            _out('email_password', 'Paste your App Password (16 characters, no spaces):')
            return
        host = s.get('wizard_imap_host', '')
        port = s.get('wizard_imap_port', '993')
        username = s.get('wizard_imap_username', '')
        retries = int(s.get('wizard_pw_retries', '0'))
        result = _check_imap(host, port, username, ans)
        if result.get('success'):
            _save(con, wizard_step='email_senders',
                  wizard_imap_password=ans, wizard_pw_retries='0')
            _out('email_senders',
                 '✅ Connected!\n\n'
                 'What sender addresses does your bank use for email notifications?\n'
                 'Separate multiple with commas.\n\n'
                 'Tip: open a bank email and check the "From" field.\n'
                 'Example: alertas@notificaciones.bancolombia.com')
        else:
            retries += 1
            _save(con, wizard_pw_retries=str(retries))
            err = result.get('error', 'connection')
            if retries >= 3:
                _save(con, wizard_step='email_address', wizard_pw_retries='0')
                _out('email_address', '❌ Too many failed attempts. Let\'s start over.\n\nWhat is your email address?')
            elif err == 'auth':
                _out('email_password',
                     f'❌ Login failed ({retries}/3). Double-check your App Password.\n\nPaste your App Password:')
            else:
                _out('email_password',
                     f'❌ Could not reach {host} ({retries}/3). Check the hostname.\n\nPaste your App Password:')
        return

    # ── email_senders ─────────────────────────────────────────────────────────
    if step == 'email_senders':
        if not ans:
            _out('email_senders',
                 'What sender addresses does your bank use?\n'
                 'Separate multiple with commas.')
            return
        provider = s.get('wizard_email_provider', 'other')
        host = s.get('wizard_imap_host', '')
        port = s.get('wizard_imap_port', '993')
        username = s.get('wizard_imap_username', '')
        password = s.get('wizard_imap_password', '')
        _save(con, wizard_bank_senders=ans)
        _save_email_config(provider, host, port, username, ans)
        _save(con, wizard_imap_password='')   # clear password from settings

        result = _check_imap(host, port, username, password, ans)
        n = result.get('unseen_from_bank', 0) if result.get('success') else 0
        prefix = f'✅ Email configured. {n} unread bank email(s) already waiting.\n\n' if n else \
                 '✅ Email configured. I\'ll capture emails as they arrive.\n\n'

        preloaded = s.get('wizard_accounts_preloaded') == 'true'
        if preloaded:
            _save(con, wizard_step='sms_choice')
            _out('sms_choice', prefix + _q_sms())
        else:
            _save(con, wizard_step='accounts_banks')
            _out('accounts_banks', prefix + _q_banks())
        return

    # ── accounts_banks ────────────────────────────────────────────────────────
    if step == 'accounts_banks':
        if not ans:
            _out('accounts_banks', _q_banks())
            return
        indices = _pick_nums(ans, len(BANKS))
        low = ans.lower()
        # Fallback: name matching
        if not indices:
            indices = [i for i, (slug, name) in enumerate(BANKS)
                       if slug in low or name.lower() in low]
        if not indices:
            _out('accounts_banks', 'Please reply with numbers (e.g. "1" or "1,3").\n\n' + _q_banks())
            return
        selected = [BANKS[i][0] for i in indices]
        first, rest = selected[0], selected[1:]
        _save(con, wizard_step='accounts_types',
              wizard_current_bank=first,
              wizard_banks_queue=json.dumps(rest),
              wizard_accounts_queue='[]')
        _out('accounts_types', _q_types(dict(BANKS)[first]))
        return

    # ── accounts_types ────────────────────────────────────────────────────────
    if step == 'accounts_types':
        current_bank = s.get('wizard_current_bank', '')
        bank_name = dict(BANKS).get(current_bank, current_bank.title())
        if not ans:
            _out('accounts_types', _q_types(bank_name))
            return
        indices = _pick_nums(ans, len(ACCT_TYPES))
        if not indices:
            _out('accounts_types', 'Please reply with numbers.\n\n' + _q_types(bank_name))
            return
        new_entries = [{'bank': current_bank, 'type': ACCT_TYPES[i][0]} for i in indices]
        queue: list[dict] = json.loads(s.get('wizard_accounts_queue', '[]')) + new_entries
        banks_remaining: list[str] = json.loads(s.get('wizard_banks_queue', '[]'))
        _save(con, wizard_accounts_queue=json.dumps(queue))
        if banks_remaining:
            next_bank = banks_remaining.pop(0)
            _save(con, wizard_current_bank=next_bank,
                  wizard_banks_queue=json.dumps(banks_remaining))
            _out('accounts_types', _q_types(dict(BANKS).get(next_bank, next_bank.title())))
        else:
            _start_next_account(con, queue)
        return

    # ── account_last4 ─────────────────────────────────────────────────────────
    if step == 'account_last4':
        current = json.loads(s.get('wizard_current_account', '{}'))
        bank_name = dict(BANKS).get(current.get('bank', ''), current.get('bank', '').title())
        if not ans:
            _out('account_last4',
                 f'What are the last 4 digits of the account number shown in {bank_name} notifications?\n'
                 '(or "skip" to leave blank)')
            return
        last4 = '' if _is_skip(ans) else re.sub(r'\D', '', ans)[-4:]
        _save(con, wizard_step='account_card' if current.get('type') in ('checking', 'credit')
              else 'account_currency', wizard_cur_last4=last4)
        if current.get('type') in ('checking', 'credit'):
            _out('account_card',
                 'What are the last 4 digits of the card linked to this account?\n'
                 '(e.g. "Tarjeta ****5678" → type 5678, or "skip")\n\n'
                 'Note: usually different from the account number above.')
        else:
            _out('account_currency', 'What currency? (e.g. COP, USD — or just type "cop" for COP)')
        return

    # ── account_card ──────────────────────────────────────────────────────────
    if step == 'account_card':
        if not ans:
            _out('account_card', 'What are the last 4 digits of the linked card? (or "skip")')
            return
        card4 = '' if _is_skip(ans) else re.sub(r'\D', '', ans)[-4:]
        _save(con, wizard_step='account_currency', wizard_cur_card=card4)
        _out('account_currency', 'What currency? (e.g. COP, USD — or just type "cop" for COP)')
        return

    # ── account_currency ──────────────────────────────────────────────────────
    if step == 'account_currency':
        cur = _currency(ans) if ans else 'COP'
        _save(con, wizard_step='account_alias', wizard_cur_currency=cur)
        _out('account_alias',
             'Give this account a nickname for summaries.\n'
             '(e.g. "Bancolombia débito", "Visa gold" — or "skip" to leave blank)')
        return

    # ── account_alias ─────────────────────────────────────────────────────────
    if step == 'account_alias':
        if not ans:
            _out('account_alias',
                 'Give this account a nickname (or "skip" to leave blank):')
            return
        alias = '' if _is_skip(ans) else ans
        current = json.loads(s.get('wizard_current_account', '{}'))
        _save_account(
            bank=current.get('bank', ''),
            acct_type=current.get('type', ''),
            currency=s.get('wizard_cur_currency', 'COP'),
            last4=s.get('wizard_cur_last4', ''),
            card4=s.get('wizard_cur_card', ''),
            alias=alias,
        )
        remaining: list[dict] = json.loads(s.get('wizard_accounts_queue', '[]'))
        _start_next_account(con, remaining)
        return

    # ── sms_choice ────────────────────────────────────────────────────────────
    if step == 'sms_choice':
        if not ans:
            _out('sms_choice', _q_sms())
            return
        if ans.strip().startswith('1') or 'yes' in ans.lower() or 'sí' in ans.lower():
            _save(con, wizard_step='sms_phone')
            _out('sms_phone', 'What phone do you use?\n\n1. iPhone\n2. Android\n3. Both')
        else:
            _finalize(con, s)
        return

    # ── sms_phone ─────────────────────────────────────────────────────────────
    if step == 'sms_phone':
        if not ans:
            _out('sms_phone', 'What phone do you use?\n\n1. iPhone\n2. Android\n3. Both')
            return
        low = ans.lower()
        tmpl = _tmpl('sms_iphone.md') if ('1' in ans or 'iphone' in low or 'ios' in low) \
            else _tmpl('sms_android.md')
        _save(con, wizard_step='sms_confirm')
        _out('sms_confirm',
             (tmpl + '\n\n' if tmpl else '') +
             'Reply when you\'ve finished and I\'ll confirm it\'s working.')
        return

    # ── sms_confirm ───────────────────────────────────────────────────────────
    if step == 'sms_confirm':
        if not ans:
            _out('sms_confirm', 'Reply when you\'ve finished setting up SMS forwarding.')
            return
        _finalize(con, s)
        return

    # Unknown / stale step — restart
    _save(con, wizard_step='welcome')
    _out('welcome', 'Let\'s start setup. How would you like to proceed?\n\n'
         '1. Full setup\n2. Accounts only')


if __name__ == '__main__':
    main()
