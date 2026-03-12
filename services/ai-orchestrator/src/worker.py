import json
import sys
import time
import traceback
import random
from typing import Any

import pika
import redis
from pika.adapters.blocking_connection import BlockingChannel
from pymongo import MongoClient

from . import config
from .locks import try_lock
from .logic import generate_reply_and_session_patch, get_last_messages, get_session, update_session_data
from .intent_classifier import classify_intent
from .logic import ensure_order


def connect_rabbit() -> tuple[pika.BlockingConnection, BlockingChannel]:
    params = pika.URLParameters(config.RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue=config.INCOMING_QUEUE, durable=True)
    channel.queue_declare(queue=config.OUTGOING_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    return connection, channel


def connect_mongo() -> MongoClient:
    return MongoClient(config.MONGO_URI)


def connect_redis() -> redis.Redis:
    return redis.from_url(config.REDIS_URL, decode_responses=True)


def publish_outgoing(channel: BlockingChannel, payload: dict[str, Any]) -> None:
    channel.basic_publish(
        exchange="",
        routing_key=config.OUTGOING_QUEUE,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )


def handle_message(channel: BlockingChannel, delivery_tag: int, db, rds: redis.Redis, event: dict[str, Any]) -> None:
    session_id = str(event.get("session_id") or "")
    if not session_id:
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
        return

    lock = try_lock(rds, f"lock:session:{session_id}", ttl_ms=config.LOCK_TTL_MS)
    if not lock:
        channel.basic_ack(delivery_tag=delivery_tag)
        return

    try:
        session = get_session(db, session_id)
        if not session:
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        if session.get("assigned_agent_id"):
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        incoming_text = str(event.get("message") or "")

        _context = get_last_messages(db, session_id, config.CONTEXT_MESSAGE_LIMIT)

        try:
            session_data = session.get("session_data") or {}
            order = ensure_order(session_data if isinstance(session_data, dict) else {})
            step = str(order.get("step") or "waiting_part_name")
            intent = classify_intent(text=incoming_text, order_step=step)
            wa_message_id = str(event.get("wa_message_id") or "")
            if wa_message_id:
                db["chat_messages"].update_one(
                    {"wa_message_id": wa_message_id},
                    {
                        "$set": {
                            "intent": intent.name,
                            "intent_confidence": float(intent.confidence),
                            "intent_data": intent.data,
                        }
                    },
                )
        except Exception:
            # Never block replies if intent tagging fails.
            pass

        replies, patch = generate_reply_and_session_patch(db, session, incoming_text)
        if patch:
            update_session_data(db, session_id, patch)

        # small delay to make replies feel more human in dev
        lo = max(0, int(config.HUMANIZE_DELAY_MS_MIN))
        hi = max(lo, int(config.HUMANIZE_DELAY_MS_MAX))
        time.sleep(random.randint(lo, hi) / 1000.0)

        wa_to = str(event.get("sender_id") or event.get("wa_to") or "")
        for i, msg in enumerate(replies):
            publish_outgoing(
                channel,
                {
                    "session_id": session_id,
                    "wa_to": wa_to,
                    "message": msg,
                },
            )
            # Help preserve message ordering (Mongo sorts by timestamp).
            if i < len(replies) - 1:
                time.sleep(0.15)

        channel.basic_ack(delivery_tag=delivery_tag)
    finally:
        lock.release()


def main() -> None:
    while True:
        try:
            mongo = connect_mongo()
            db = mongo[config.MONGO_DB]
            rds = connect_redis()
            conn, channel = connect_rabbit()

            def on_message(ch: BlockingChannel, method, _props, body: bytes):
                try:
                    event = json.loads(body.decode("utf-8"))
                except Exception:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    return

                try:
                    handle_message(ch, method.delivery_tag, db, rds, event)
                except Exception as exc:
                    print("worker error:", repr(exc), file=sys.stderr)
                    traceback.print_exc()
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_consume(queue=config.INCOMING_QUEUE, on_message_callback=on_message, auto_ack=False)
            print("ai-orchestrator consuming", config.INCOMING_QUEUE)
            channel.start_consuming()
        except Exception as exc:
            print("ai-orchestrator crashed, retrying:", repr(exc), file=sys.stderr)
            traceback.print_exc()
            time.sleep(3)


if __name__ == "__main__":
    main()
