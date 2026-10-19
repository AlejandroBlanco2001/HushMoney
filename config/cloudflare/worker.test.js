import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { describe, it } from 'node:test';

import worker from './worker.js';

const SECRET = 'TEST_SECRET_VALUE_abc123';
const WEBHOOK_URL = 'https://forwarder.test/channels/email';

const loadFixture = (name) =>
  readFile(new URL(`../../tests/fixtures/emails/bancolombia/${name}.eml`, import.meta.url), 'utf8');

const makeEnv = (overrides = {}) => ({
  EMAIL_WEBHOOK_URL: WEBHOOK_URL,
  EMAIL_WEBHOOK_SECRET: SECRET,
  ...overrides,
});

async function runEmail({
  raw,
  from = 'alerts@bank.test',
  headers = new Headers(),
  env = makeEnv(),
  fetchImpl = async () => new Response('ok', { status: 200 }),
}) {
  const fetchCalls = [];
  const consoleCalls = [];
  const original = { fetch: globalThis.fetch, log: console.log, error: console.error };

  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    return fetchImpl(url, options);
  };
  console.log = (...args) => consoleCalls.push({ level: 'log', args });
  console.error = (...args) => consoleCalls.push({ level: 'error', args });

  try {
    await worker.email({ raw, from, headers }, env, {});
  } finally {
    globalThis.fetch = original.fetch;
    console.log = original.log;
    console.error = original.error;
  }

  return { fetchCalls, consoleCalls };
}

const loggedText = (consoleCalls) =>
  consoleCalls.flatMap((call) => call.args.map(String)).join(' ');

describe('email dispatch', () => {
  it('POSTs the parsed payload to the forwarder with the shared-secret header', async () => {
    const raw = await loadFixture('compra_debito');
    const { fetchCalls, consoleCalls } = await runEmail({ raw });

    assert.equal(fetchCalls.length, 1);
    const [{ url, options }] = fetchCalls;
    assert.equal(url, WEBHOOK_URL);
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.equal(options.headers.Authorization, `Bearer ${SECRET}`);

    const payload = JSON.parse(options.body);
    assert.deepEqual(Object.keys(payload).sort(), ['body', 'from', 'subject']);
    assert.equal(payload.from, 'alertasynotificaciones@ayn.notificacionesbancolombia.com');
    assert.equal(payload.subject, 'Alertas y Notificaciones');
    assert.match(payload.body, /Compraste \$47\.350,00 en Rappi/);

    assert.match(loggedText(consoleCalls), /Dispatched to forwarder/);
  });

  it('dispatches a second fixture with its own sender and body', async () => {
    const raw = await loadFixture('transferencia_recibida');
    const { fetchCalls } = await runEmail({ raw });

    assert.equal(fetchCalls.length, 1);
    const payload = JSON.parse(fetchCalls[0].options.body);
    assert.equal(payload.from, 'alertasynotificaciones@an.notificacionesbancolombia.com');
    assert.equal(payload.subject, 'Alertas y Notificaciones');
    assert.match(payload.body, /recibiste una transferencia de JUAN PEREZ/);
  });
});

describe('configuration guards', () => {
  it('drops the email when EMAIL_WEBHOOK_URL is missing', async () => {
    const raw = await loadFixture('compra_debito');
    const { fetchCalls, consoleCalls } = await runEmail({
      raw,
      env: makeEnv({ EMAIL_WEBHOOK_URL: undefined }),
    });

    assert.equal(fetchCalls.length, 0);
    assert.match(loggedText(consoleCalls), /not configured/);
  });

  it('drops the email when EMAIL_WEBHOOK_SECRET is missing', async () => {
    const raw = await loadFixture('compra_debito');
    const { fetchCalls, consoleCalls } = await runEmail({
      raw,
      env: makeEnv({ EMAIL_WEBHOOK_SECRET: undefined }),
    });

    assert.equal(fetchCalls.length, 0);
    assert.match(loggedText(consoleCalls), /not configured/);
  });

  it('refuses to dispatch whatever EMAIL_WEBHOOK_URL wrangler.toml currently ships', async () => {
    const toml = await readFile(new URL('./wrangler.toml', import.meta.url), 'utf8');
    const match = toml.match(/^EMAIL_WEBHOOK_URL\s*=\s*"([^"]+)"/m);
    assert.ok(match, 'wrangler.toml must define EMAIL_WEBHOOK_URL');

    const raw = await loadFixture('compra_debito');
    const { fetchCalls } = await runEmail({
      raw,
      env: makeEnv({ EMAIL_WEBHOOK_URL: match[1] }),
    });

    // While the config still holds a placeholder the worker must refuse;
    // once a real endpoint is configured it must dispatch to it.
    const stillPlaceholder = /REPLACE/.test(match[1]);
    assert.equal(fetchCalls.length, stillPlaceholder ? 0 : 1);
    if (!stillPlaceholder) {
      assert.equal(fetchCalls[0].url, match[1]);
    }
  });
});

describe('input guards', () => {
  it('drops an email whose text part is empty', async () => {
    const raw = [
      'From: alerts@bank.test',
      'Subject: Alert',
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset=UTF-8',
      '',
      '',
    ].join('\r\n');

    const { fetchCalls, consoleCalls } = await runEmail({ raw });

    assert.equal(fetchCalls.length, 0);
    assert.match(loggedText(consoleCalls), /Email body empty after parse/);
  });

  it('drops an HTML-only email without attempting dispatch (current behavior)', async () => {
    const raw = [
      'From: alerts@bank.test',
      'Subject: Alert',
      'MIME-Version: 1.0',
      'Content-Type: text/html; charset=UTF-8',
      '',
      '<p>Your account was debited</p>',
    ].join('\r\n');

    const { fetchCalls, consoleCalls } = await runEmail({ raw });

    assert.equal(fetchCalls.length, 0);
    assert.match(loggedText(consoleCalls), /Email body empty after parse/);
  });

  it('logs and drops a malformed message without leaking its content', async () => {
    const raw = [
      'From: alerts@bank.test',
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset=UTF-8',
      '',
      'Secret transfer details 987654',
    ].join('\r\n');

    // No Subject header and a message without headers makes the parse
    // step fail — the branch PostalMime itself rarely reaches.
    const { fetchCalls, consoleCalls } = await runEmail({ raw, headers: null });

    assert.equal(fetchCalls.length, 0);
    assert.match(loggedText(consoleCalls), /Email parse failed/);
    assert.doesNotMatch(loggedText(consoleCalls), /987654/);
  });
});

describe('dispatch failure', () => {
  it('drops the message without retrying when fetch rejects', async () => {
    const raw = await loadFixture('compra_debito');
    const { fetchCalls, consoleCalls } = await runEmail({
      raw,
      fetchImpl: async () => {
        throw new TypeError('fetch failed');
      },
    });

    assert.equal(fetchCalls.length, 1);
    assert.match(loggedText(consoleCalls), /Forwarder dispatch failed/);
  });

  it('drops the message without retrying when the forwarder answers 500', async () => {
    const raw = await loadFixture('compra_debito');
    const { fetchCalls, consoleCalls } = await runEmail({
      raw,
      fetchImpl: async () => new Response('boom', { status: 500 }),
    });

    assert.equal(fetchCalls.length, 1);
    assert.match(loggedText(consoleCalls), /Forwarder rejected email status=500/);
  });
});

describe('security: log hygiene', () => {
  it('never logs the webhook secret in any scenario', async () => {
    const raw = await loadFixture('compra_debito');
    const scenarios = [
      { raw },
      { raw, env: makeEnv({ EMAIL_WEBHOOK_URL: undefined }) },
      { raw, env: makeEnv({ EMAIL_WEBHOOK_URL: 'https://REPLACE_ME/channels/email' }) },
      { raw, fetchImpl: async () => new Response('boom', { status: 500 }) },
      {
        raw,
        fetchImpl: async () => {
          throw new TypeError('fetch failed');
        },
      },
    ];

    const allLogs = [];
    for (const scenario of scenarios) {
      const { consoleCalls } = await runEmail(scenario);
      allLogs.push(loggedText(consoleCalls));
    }

    assert.doesNotMatch(allLogs.join('\n'), new RegExp(SECRET));
  });

  it('never logs email content (body or subject) in any scenario', async () => {
    const raw = await loadFixture('compra_debito');
    const { consoleCalls } = await runEmail({ raw });
    const logged = loggedText(consoleCalls);

    assert.doesNotMatch(logged, /Compraste/);
    assert.doesNotMatch(logged, /47\.350/);
    assert.doesNotMatch(logged, /Alertas y Notificaciones/);
  });
});
