import PostalMime from "postal-mime";

const PLACEHOLDER_WEBHOOK_URL = "https://REPLACE_ME/channels/email";

function isWebhookConfigured(env) {
  const url = env.EMAIL_WEBHOOK_URL;
  const secret = env.EMAIL_WEBHOOK_SECRET;
  return Boolean(url) && url !== PLACEHOLDER_WEBHOOK_URL && Boolean(secret);
}

function senderAddress(parsed, message) {
  return parsed.from?.address || message.from || "";
}

async function parseInboundEmail(message) {
  const parsed = await PostalMime.parse(message.raw);
  const body = (parsed.text || "").trim();
  if (!body) {
    return null;
  }
  return {
    from: senderAddress(parsed, message),
    subject: parsed.subject || message.headers.get("subject") || "",
    body,
  };
}

async function postToForwarder(env, payload) {
  return fetch(env.EMAIL_WEBHOOK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.EMAIL_WEBHOOK_SECRET}`,
    },
    body: JSON.stringify(payload),
  });
}

export default {
  async email(message, env, _ctx) {
    if (!isWebhookConfigured(env)) {
      console.error("Email webhook not configured");
      return;
    }

    let payload;
    try {
      payload = await parseInboundEmail(message);
    } catch {
      console.error("Email parse failed");
      return;
    }

    if (payload === null) {
      console.error("Email body empty after parse");
      return;
    }

    let response;
    try {
      response = await postToForwarder(env, payload);
    } catch {
      console.error("Forwarder dispatch failed");
      return;
    }
    
    if (!response.ok) {
      console.error(`Forwarder rejected email status=${response.status}`);
      return;
    }
    console.log("Dispatched to forwarder");

  },
};
