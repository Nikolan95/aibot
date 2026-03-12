#!/usr/bin/env bash
set -euo pipefail

# Drops the old UNIQUE index on chat_carts.session_id.
# We want to keep cart history by allowing multiple carts per chat session.

docker compose exec -T mongo mongosh --quiet "${MONGO_INITDB_DATABASE:-aibot}" --eval '
const coll = db.getCollection("chat_carts");
const indexes = coll.getIndexes();
let dropped = 0;
for (const ix of indexes) {
  if (ix && ix.unique === true && ix.key && ix.key.session_id === 1) {
    print(`Dropping unique index: ${ix.name}`);
    coll.dropIndex(ix.name);
    dropped++;
  }
}
if (dropped === 0) print("No unique session_id index found on chat_carts (nothing to do).");
'

echo "Done."
