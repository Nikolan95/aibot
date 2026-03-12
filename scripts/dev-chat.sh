#!/usr/bin/env bash
set -euo pipefail

phone="${1:-}"
shift || true
text="${*:-}"

if [[ -z "${phone}" || -z "${text}" ]]; then
  echo "Usage: scripts/dev-chat.sh <phone> <message...>" >&2
  echo "Example: scripts/dev-chat.sh +15551234567 \"VIN 1HGCM82633A004352\"" >&2
  exit 2
fi

phone_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${phone}")"
text_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${text}")"
wa_message_id="$(python3 -c 'import time,uuid; print("wamid.local.%d.%s" % (int(time.time()*1000), uuid.uuid4().hex))')"

curl -sS -X POST "http://localhost:3000/webhook" \
  -H 'content-type: application/json' \
  -d "{
    \"entry\":[{\"changes\":[{\"value\":{
      \"messages\":[{\"id\":\"${wa_message_id}\",\"from\":${phone_json},\"type\":\"text\",\"text\":{\"body\":${text_json}}}]
    }}]}]
  }" >/dev/null

# give the worker a moment
sleep 0.6

session_id="$(
  docker compose exec -T mongo mongosh --quiet aibot --eval "
    const s=db.chat_sessions.findOne({sender_id: ${phone_json}}, {_id:1});
    if(!s){ quit(3); }
    print(s._id.valueOf());
  "
)"

docker compose exec -T mongo mongosh --quiet aibot --eval "
  const sid=ObjectId(\"${session_id}\");
  const msgs=db.chat_messages.find({session_id:sid}).sort({timestamp:1}).toArray();
  for (const m of msgs.slice(-12)) {
    print(\`\${m.sender_type}: \${m.message}\`);
  }
"
