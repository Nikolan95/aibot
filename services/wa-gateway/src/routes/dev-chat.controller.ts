import { Body, Controller, Get, Post, Query } from '@nestjs/common';
import crypto = require('crypto');
import { InboundMessageService } from '../services/inbound-message.service';

@Controller('/dev/chat')
export class DevChatController {
  constructor(private readonly inbound: InboundMessageService) {}

  @Get()
  page() {
    return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AI WhatsApp Bot - Dev Chat</title>
    <style>
      :root { color-scheme: light dark; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 0; }
      .wrap { max-width: 1100px; margin: 0 auto; padding: 16px; display: grid; gap: 12px; }
      .top { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
      label { display: grid; gap: 6px; font-size: 12px; opacity: 0.9; }
      input, button { font: inherit; padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(127,127,127,.35); background: transparent; }
      button { cursor: pointer; }
      .main { display: grid; grid-template-columns: 1fr 320px; gap: 12px; align-items: start; }
      .chat { border: 1px solid rgba(127,127,127,.35); border-radius: 14px; padding: 12px; height: 520px; overflow: auto; background: rgba(127,127,127,.06); }
      .side { border: 1px solid rgba(127,127,127,.35); border-radius: 14px; padding: 12px; background: rgba(127,127,127,.06); }
      .side h3 { margin: 0 0 10px; font-size: 14px; }
      .cart-item { padding: 10px; border-radius: 12px; border: 1px solid rgba(127,127,127,.25); background: rgba(127,127,127,.08); margin-bottom: 10px; }
      .cart-title { font-weight: 600; font-size: 13px; }
      .cart-meta { font-size: 12px; opacity: 0.85; margin-top: 4px; }
      .row { display: flex; margin: 8px 0; }
      .bubble { padding: 10px 12px; border-radius: 14px; max-width: 76%; white-space: pre-wrap; word-break: break-word; }
      .customer { justify-content: flex-end; }
      .customer .bubble { background: #2563eb; color: white; }
      .bot .bubble { background: rgba(127,127,127,.18); }
      .meta { font-size: 11px; opacity: .75; margin-top: 4px; }
      .send { display: flex; gap: 10px; }
      .send input { flex: 1; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h2 style="margin: 6px 0 0;">Dev Chat Simulator</h2>
      <div class="top">
        <label>
          Sender (phone)
          <input id="sender" placeholder="+15551234567" />
        </label>
        <button id="connect">Connect</button>
        <div style="flex:1"></div>
        <div class="meta">API: <code>/dev/chat/messages</code></div>
      </div>
      <div class="main">
        <div id="chat" class="chat" aria-live="polite"></div>
        <div class="side">
          <h3>Cart (debug)</h3>
          <div id="cart"></div>
        </div>
      </div>

      <div class="send">
        <input id="msg" placeholder="Type a message…" />
        <button id="send">Send</button>
      </div>
      <div id="status" class="meta">Loading…</div>
      <div id="typing" class="meta"></div>
      <div class="meta">Tip: send a VIN like <code>1HGCM82633A004352</code> to start.</div>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);
      const chatEl = $("chat");
      const senderEl = $("sender");
      const msgEl = $("msg");
      const connectBtn = $("connect");
      const sendBtn = $("send");
      const statusEl = $("status");
      const typingEl = $("typing");
      const cartEl = $("cart");

	      const apiBase = location.origin;
	      const storage = {
	        get(key) { try { return localStorage.getItem(key); } catch (_e) { return null; } },
	        set(key, val) { try { localStorage.setItem(key, val); } catch (_e) {} }
	      };

      let sender = storage.get("dev_sender") || "+15551234567";
      senderEl.value = sender;
      let pollTimer = null;
      let lastHash = "";
      let typingUntil = 0;
      let lastSendAt = 0;

		      function escapeHtml(s) {
		        const ent = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
		        return String(s).replace(/[&<>"']/g, (c) => ent[c] || c);
		      }

      function render(messages) {
        const hash = JSON.stringify(messages.map(m => [m.sender_type, m.message, m.timestamp]));
        if (hash === lastHash) return;
        lastHash = hash;

        chatEl.innerHTML = messages.map(m => {
          const cls = m.sender_type === "customer" ? "customer" : (m.sender_type === "bot" ? "bot" : "bot");
          const label = m.sender_type === "customer" ? "You" : (m.sender_type === "bot" ? "Bot" : m.sender_type);
          const ts = m.timestamp ? new Date(m.timestamp).toLocaleString() : "";
          const intent = m.intent ? String(m.intent) : "";
          const intentBadge = intent ? \`<span style="margin-left:8px;padding:2px 8px;border:1px solid rgba(127,127,127,.35);border-radius:999px;font-size:11px;opacity:.85;">\${escapeHtml(intent)}</span>\` : "";
          return \`
            <div class="row \${cls}">
              <div>
                <div class="bubble">\${escapeHtml(m.message || "")}</div>
                <div class="meta">\${escapeHtml(label)} • \${escapeHtml(ts)} \${intentBadge}</div>
              </div>
            </div>\`;
        }).join("");
        chatEl.scrollTop = chatEl.scrollHeight;
      }

      async function fetchMessages() {
        if (!sender) return;
        try {
          const res = await fetch(\`\${apiBase}/dev/chat/messages?sender_id=\${encodeURIComponent(sender)}\`);
          if (!res.ok) throw new Error(\`HTTP \${res.status}\`);
          const data = await res.json();
          render(data.messages || []);
          statusEl.textContent = \`Connected as \${sender}\`;

          const msgs = data.messages || [];
          const lastBot = [...msgs].reverse().find(m => m && m.sender_type === "bot");
          const lastBotTs = lastBot && lastBot.timestamp ? Date.parse(lastBot.timestamp) : 0;
          if (Date.now() < typingUntil && lastBotTs < lastSendAt) {
            typingEl.textContent = "Bot is typing…";
          } else {
            typingEl.textContent = "";
          }
        } catch (e) {
          statusEl.textContent = \`Error: \${e && e.message ? e.message : e}\`;
        }
      }

      function renderCart(items) {
        const list = Array.isArray(items) ? items : [];
        if (!list.length) {
          cartEl.innerHTML = '<div class="meta">Cart is empty.</div>';
          return;
        }
        cartEl.innerHTML = list.slice(-20).reverse().map((it) => {
          const title = (it && it.title) ? String(it.title) : "Item";
          const oem = it && it.oem ? String(it.oem) : "";
          const brand = it && it.brand ? String(it.brand) : "";
          const qty = it && it.qty ? String(it.qty) : "1";
          return \`
            <div class="cart-item">
              <div class="cart-title">\${escapeHtml(title)}</div>
              <div class="cart-meta">\${escapeHtml([brand, oem ? ("OEM " + oem) : "", "Qty " + qty].filter(Boolean).join(" • "))}</div>
            </div>\`;
        }).join("");
      }

      async function fetchCart() {
        if (!sender) return;
        try {
          const res = await fetch(\`\${apiBase}/dev/chat/cart?sender_id=\${encodeURIComponent(sender)}\`);
          if (!res.ok) return;
          const data = await res.json();
          renderCart(data.items || []);
        } catch (_e) {}
      }

      function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(() => { fetchMessages(); fetchCart(); }, 900);
        fetchMessages();
        fetchCart();
      }

      connectBtn.addEventListener("click", () => {
        sender = senderEl.value.trim();
        if (!sender) return;
        storage.set("dev_sender", sender);
        lastHash = "";
        startPolling();
        msgEl.focus();
      });

      async function send() {
        sender = senderEl.value.trim();
        const text = msgEl.value;
        if (!sender || !text.trim()) return;

        msgEl.value = "";
        lastSendAt = Date.now();
        typingUntil = lastSendAt + 12000;
        typingEl.textContent = "Bot is typing…";
        try {
          const res = await fetch(\`\${apiBase}/dev/chat/messages\`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ sender_id: sender, message: text })
          });
          if (!res.ok) throw new Error(\`HTTP \${res.status}\`);
        } catch (e) {
          statusEl.textContent = \`Send failed: \${e && e.message ? e.message : e}\`;
        }
        await fetchMessages();
        await fetchCart();
      }

      sendBtn.addEventListener("click", send);
      msgEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") send();
      });

      startPolling();
    </script>
  </body>
</html>`;
  }

  @Get('/messages')
  async messages(@Query('sender_id') senderId: string) {
    return this.inbound.getHistory(senderId, 50);
  }

  @Get('/cart')
  async cart(@Query('sender_id') senderId: string) {
    return this.inbound.getCart(senderId);
  }

  @Post('/messages')
  async send(@Body() body: { sender_id?: string; message?: string }) {
    const senderId = String(body.sender_id ?? '').trim();
    const message = String(body.message ?? '').trim();
    if (!senderId || !message) return { ok: false };

    const waMessageId = `wamid.dev.${Date.now()}.${crypto.randomBytes(6).toString('hex')}`;
    await this.inbound.processIncoming({
      wa_message_id: waMessageId,
      sender_phone: senderId,
      message_type: 'text',
      message,
      wa_to: 'dev',
    });
    return { ok: true };
  }
}
