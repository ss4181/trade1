"""Standalone SQLite archive/outbox; never reads the original bot's state."""
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS candles (
            market TEXT, coin TEXT, interval TEXT, t INTEGER, body TEXT,
            PRIMARY KEY(market,coin,interval,t));
        CREATE TABLE IF NOT EXISTS snapshots (t INTEGER PRIMARY KEY, body TEXT);
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, t INTEGER, body TEXT, delivered INTEGER,
            attempts INTEGER DEFAULT 0, next_attempt INTEGER DEFAULT 0);
        ''')

    def put_candles(self, market, coin, interval, rows):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?)',
                [(market,coin,interval,r['t'],json.dumps(r)) for r in rows])

    def candles(self, market, coin, interval):
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT body FROM candles WHERE market=? AND coin=? AND interval=? ORDER BY t',
            (market,coin,interval))]

    def snapshot(self, t, body):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?)', (t,json.dumps(body)))

    def latest(self):
        row = self.db.execute('SELECT t,body FROM snapshots ORDER BY t DESC LIMIT 1').fetchone()
        return (row[0],json.loads(row[1])) if row else (None,None)

    def add_event(self, event):
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO events(id,t,body,delivered) VALUES(?,?,?,NULL)',
                                    (event['id'], event['detected_ms'], json.dumps(event)))
        return cursor.rowcount == 1

    def recent(self, strategy, coin, after):
        return any(json.loads(r[0]).get('strategy') == strategy and
                   json.loads(r[0]).get('coin') == coin for r in self.db.execute(
                       'SELECT body FROM events WHERE t>?', (after,)))

    def pending(self, now):
        return [(r[0],json.loads(r[1]),r[2]) for r in self.db.execute(
            'SELECT id,body,attempts FROM events WHERE delivered IS NULL AND attempts<4 AND next_attempt<=? ORDER BY t',
            (now,))]

    def events(self, limit=5000):
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT body FROM events ORDER BY t DESC LIMIT ?', (limit,))]

    def delivery(self, eid, now, ok):
        with self.db:
            self.db.execute('UPDATE events SET attempts=attempts+1,next_attempt=?,delivered=? WHERE id=?',
                            (now+60000, now if ok else None,eid))

    def close(self):
        self.db.close()


def read_delivery_status(path):
    if not Path(path).exists():
        return {'events':0}
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        row=db.execute('''SELECT COUNT(*),
            SUM(CASE WHEN delivered IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN delivered IS NULL AND attempts<4 THEN 1 ELSE 0 END),
            SUM(CASE WHEN delivered IS NULL AND attempts>=4 THEN 1 ELSE 0 END),
            MAX(delivered) FROM events''').fetchone()
        return dict(zip(['events','acknowledged','pending','failed_or_expired','last_ack_ms'],
                        [row[0],row[1] or 0,row[2] or 0,row[3] or 0,row[4]]))
    finally:
        db.close()
