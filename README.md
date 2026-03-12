# WhatsApp Car Parts Ordering Chatbot (Local Dev)

This repo contains a local Docker dev stack based on the spec in `docs/whatsapp-car-parts-chatbot.txt`.

## Services

- `wa-gateway` (NestJS): Meta WhatsApp webhook receiver + outbound sender
- `ai-orchestrator` (Python): consumes incoming message events and produces bot replies
- `mongo`, `rabbitmq`, `redis`, `minio`

## Quickstart

1) (Optional) Create env file (Compose has defaults if you skip this):

```bash
cp .env.example .env
```

2) Start the stack:

```bash
docker compose up --build
```

3) Test webhook (local simulated payload):

```bash
curl -sS -X POST http://localhost:3000/webhook \\
  -H 'content-type: application/json' \\
  -d '{
    "entry":[{"changes":[{"value":{
      "messages":[{"id":"wamid.local.1","from":"+15551234567","type":"text","text":{"body":"VIN 1HGCM82633A004352"}}]
    }}]}]
  }'
```

You should see the `ai-orchestrator` produce a reply and `wa-gateway` store/send it (logged in container output).

## Dev chat helper

With the stack running, you can "chat" by simulating WhatsApp inbound messages and printing the last messages from MongoDB:

```bash
chmod +x scripts/dev-chat.sh
scripts/dev-chat.sh +15551234567 "VIN 1HGCM82633A004352"
scripts/dev-chat.sh +15551234567 "Brake pads"
scripts/dev-chat.sh +15551234567 "2"
scripts/dev-chat.sh +15551234567 "123 Main St, Miami, FL"
scripts/dev-chat.sh +15551234567 "YES"
```

## Enable OpenAI (human-like smalltalk)

The AI worker can use OpenAI for smalltalk/general questions (while keeping VIN/order logic deterministic).

1) Set:

- `OPENAI_API_KEY` in `/opt/homebrew/var/www/aibot/.env`
- optional `OPENAI_MODEL` (default `gpt-5-mini`)

2) Restart:

```bash
docker compose up -d --build ai-orchestrator
```

## Notes

- Real Meta signature verification is enabled only when `WA_APP_SECRET` is set.
- Real message sending is enabled only when `WA_ACCESS_TOKEN` and `WA_PHONE_NUMBER_ID` are set; otherwise outbound sends are logged and stored with a synthetic `wa_message_id`.
