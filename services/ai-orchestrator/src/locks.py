import uuid
from dataclasses import dataclass

import redis


@dataclass(frozen=True)
class RedisLock:
    client: redis.Redis
    key: str
    token: str

    def release(self) -> None:
        script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
          return redis.call("DEL", KEYS[1])
        else
          return 0
        end
        """
        self.client.eval(script, 1, self.key, self.token)


def try_lock(client: redis.Redis, key: str, ttl_ms: int) -> RedisLock | None:
    token = str(uuid.uuid4())
    ok = client.set(key, token, nx=True, px=ttl_ms)
    if not ok:
        return None
    return RedisLock(client=client, key=key, token=token)
