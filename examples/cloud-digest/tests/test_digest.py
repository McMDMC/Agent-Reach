from types import SimpleNamespace

from app import main, sources
from app.sources import Item


def test_item_id_is_stable_per_url():
    a = Item(source="s", kind="rss", title="A", url="https://x/1")
    b = Item(source="t", kind="rss", title="B", url="https://x/1")
    assert a.id == b.id
    assert Item(source="s", kind="rss", title="A", url="https://x/2").id != a.id


def test_dedupe_keeps_first_occurrence():
    a = Item(source="s", kind="rss", title="first", url="https://x/1")
    b = Item(source="t", kind="youtube", title="second", url="https://x/1")
    assert [i.title for i in main.dedupe([a, b])] == ["first"]


class _Entry(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def test_fetch_rss_maps_entries(monkeypatch):
    entry = _Entry(
        title=" Release ",
        link="https://x/r",
        summary="s",
        published_parsed=(2026, 10, 1, 12, 0, 0, 0, 0, 0),
    )
    monkeypatch.setattr(
        sources.feedparser,
        "parse",
        lambda url: SimpleNamespace(bozo=False, entries=[entry]),
    )
    [item] = sources.fetch_rss(["https://feed"])
    assert item.title == "Release"
    assert item.published.startswith("2026-10-01T12:00:00")


def test_fetch_rss_raises_on_unreadable_feed(monkeypatch):
    monkeypatch.setattr(
        sources.feedparser,
        "parse",
        lambda url: SimpleNamespace(bozo=True, entries=[], bozo_exception="boom"),
    )
    try:
        sources.fetch_rss(["https://bad"])
    except RuntimeError as exc:
        assert "unreadable" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_fetch_youtube_parses_json_lines(monkeypatch):
    out = '{"id": "abc", "title": "T", "description": "d"}\n'
    monkeypatch.setattr(
        sources.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""),
    )
    [item] = sources.fetch_youtube(["q"])
    assert item.url == "https://www.youtube.com/watch?v=abc"
    assert item.source == "youtube:q"


def test_fetch_youtube_failure_raises(monkeypatch):
    monkeypatch.setattr(
        sources.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="err"),
    )
    try:
        sources.fetch_youtube(["q"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")


def test_build_prompt_lists_every_item():
    items = [Item(source="s", kind="rss", title="T1", url="https://x/1")]
    assert "T1 — https://x/1" in main.build_prompt(items)
