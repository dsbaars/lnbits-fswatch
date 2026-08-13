from lnbits.db import Database

from .models import SETTINGS_ID, StoredWatchSettings, WatchEvent

db = Database("ext_fswatch")


async def get_settings() -> StoredWatchSettings | None:
    return await db.fetchone(
        "SELECT * FROM fswatch.settings WHERE id = :id",
        {"id": SETTINGS_ID},
        StoredWatchSettings,
    )


async def create_settings(data: StoredWatchSettings) -> StoredWatchSettings:
    await db.insert("fswatch.settings", data)
    return data


async def update_settings(data: StoredWatchSettings) -> StoredWatchSettings:
    await db.update("fswatch.settings", data)
    return data


async def create_event(event: WatchEvent) -> WatchEvent:
    await db.insert("fswatch.events", event)
    return event


async def update_event(event: WatchEvent) -> WatchEvent:
    await db.update("fswatch.events", event)
    return event


async def get_events(limit: int = 100) -> list[WatchEvent]:
    return await db.fetchall(
        "SELECT * FROM fswatch.events ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
        WatchEvent,
    )


async def delete_events() -> None:
    await db.execute("DELETE FROM fswatch.events")


async def prune_events(keep: int = 500) -> None:
    await db.execute(
        """
            DELETE FROM fswatch.events WHERE id NOT IN (
                SELECT id FROM fswatch.events ORDER BY created_at DESC LIMIT :keep
            )
        """,
        {"keep": keep},
    )
