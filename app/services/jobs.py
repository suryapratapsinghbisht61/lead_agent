"""Live run progress in Redis.

The worker writes the latest progress event for a run into a Redis hash
(run:<id>:progress) and also publishes it on a channel (run:<id>:events), so
the API, or later a frontend via SSE, can show "researching lead 4/10" live.
Permanent results still go to the database; Redis only holds short-lived state.
"""

import json
import time

PROGRESS_TTL_SECONDS = 24 * 3600


def progress_key(run_id: str) -> str:
    return f"run:{run_id}:progress"


def events_channel(run_id: str) -> str:
    return f"run:{run_id}:events"


async def set_progress(redis, run_id: str, event: dict) -> None:
    data = {
        "stage": str(event.get("stage", "")),
        "message": str(event.get("message", "")),
        "updated_at": str(time.time()),
    }
    if "qualified" in event:
        data["qualified"] = str(event["qualified"])
    if "target" in event:
        data["target"] = str(event["target"])
    key = progress_key(run_id)
    await redis.hset(key, mapping=data)
    await redis.expire(key, PROGRESS_TTL_SECONDS)
    await redis.publish(events_channel(run_id), json.dumps(data))


async def get_progress(redis, run_id: str) -> dict | None:
    raw = await redis.hgetall(progress_key(run_id))
    if not raw:
        return None
    return {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()}
