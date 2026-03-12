#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f "docs/faq.seed.json" ]]; then
  echo "Missing docs/faq.seed.json" >&2
  exit 2
fi

js="$(
  python3 - <<'PY'
import json
from pathlib import Path
items=json.loads(Path("docs/faq.seed.json").read_text(encoding="utf-8"))
print("const items = " + json.dumps(items, ensure_ascii=False) + ";")
PY
)"

docker compose exec -T mongo mongosh --quiet aibot --eval "
${js}
db.faqs.createIndex({question:'text', answer:'text'}, {name:'faq_text'});
db.faqs.createIndex({question:1}, {unique:true, name:'faq_question_unique'});
for (const it of items) {
  db.faqs.updateOne(
    {question: it.question},
    {\$set: {answer: it.answer, enabled: true, updated_at: new Date()}, \$setOnInsert: {created_at: new Date()}},
    {upsert:true}
  );
}
print('seeded', items.length);
"

