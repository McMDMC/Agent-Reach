"""Zero-login collectors: RSS/Atom feeds and YouTube search.

Reddit and Twitter need a logged-in session, which a headless Cloud Run job
does not have, so they are deliberately not used here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser


@dataclass(frozen=True)
class Item:
    source: str  # feed URL or "youtube:<query>"
    kind: str  # "rss" | "youtube"
    title: str
    url: str
    summary: str = ""
    published: str | None = None
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def id(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:32]

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published": self.published,
            "collected_at": self.collected_at,
        }


def fetch_rss(feed_urls: list[str], limit: int = 15) -> list[Item]:
    items: list[Item] = []
    for feed_url in feed_urls:
        parsed = feedparser.parse(feed_url)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"feed unreadable: {feed_url}: {parsed.bozo_exception}")
        for entry in parsed.entries[:limit]:
            link = entry.get("link")
            if not link:
                continue
            published = None
            if entry.get("published_parsed"):
                published = datetime(
                    *entry.published_parsed[:6], tzinfo=timezone.utc
                ).isoformat()
            items.append(
                Item(
                    source=feed_url,
                    kind="rss",
                    title=entry.get("title", "").strip(),
                    url=link,
                    summary=(entry.get("summary") or "")[:1000],
                    published=published,
                )
            )
    return items


def fetch_youtube(queries: list[str], limit: int = 5) -> list[Item]:
    items: list[Item] = []
    for query in queries:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", f"ytsearch{limit}:{query}"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed for {query!r}: {proc.stderr.strip()[-300:]}")
        for line in proc.stdout.splitlines():
            video = json.loads(line)
            url = video.get("url") or f"https://www.youtube.com/watch?v={video['id']}"
            items.append(
                Item(
                    source=f"youtube:{query}",
                    kind="youtube",
                    title=video.get("title", ""),
                    url=url,
                    summary=(video.get("description") or "")[:1000],
                )
            )
    return items
