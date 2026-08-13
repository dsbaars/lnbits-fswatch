async def m001_initial(db):
    """
    Settings (single row) and the event log.
    """

    await db.execute(f"""
        CREATE TABLE fswatch.settings (
            id TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT false,
            webhook_url TEXT NOT NULL DEFAULT '',
            webhook_secret TEXT NOT NULL DEFAULT '',
            interval_seconds INTEGER NOT NULL DEFAULT 60,
            probe_status BOOLEAN NOT NULL DEFAULT true,
            failure_threshold INTEGER NOT NULL DEFAULT 2,
            notify_admin BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
    """)

    await db.execute(f"""
        CREATE TABLE fswatch.events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            funding_source TEXT NOT NULL,
            previous_funding_source TEXT,
            configured_funding_source TEXT,
            healthy BOOLEAN NOT NULL DEFAULT true,
            error TEXT,
            balance_msat INTEGER,
            webhook_status TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
    """)
