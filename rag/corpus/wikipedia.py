"""Build a pinned Wikipedia evidence corpus (DESIGN-LOG D-04).

Reproducibility is the point. The proposal commits to "a fixed corpus of
publicly available reference material ... allowing our RAG experiments to
remain reproducible", and Wikipedia article text changes daily. So we fetch
each article once and record its **revision ID**. A manifest of
(title, revision_id, url) is committed to git; the article text itself is
gitignored because it is large and regenerable from the manifest.

**The text file is the reproducible artifact, not the manifest.** The original
design assumed a corpus could be regenerated from pinned revision IDs. It
cannot: the MediaWiki plaintext extract (`explaintext`) is only served for an
article's *current* revision. Asking for an old revision's content returns raw
wikitext instead -- 119,907 characters of `{{templates}}` and `[[links]]` where
the extract gave 38,142 of clean prose -- and asking `extracts` for a revision
id silently returns today's text. So `articles.jsonl` is committed, and the
manifest's job is to *detect drift* (`check_drift`), not to regenerate.

Uses the MediaWiki Action API, which needs no key. Wikipedia's User-Agent
policy requires a descriptive agent, set below.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

API = "https://en.wikipedia.org/w/api.php"

# Wikipedia blocks generic agents; identify the project and a contact.
USER_AGENT = (
    "CS4701-YouTube-Community/0.1 (Cornell CS 4701 course project; kd497@cornell.edu)"
)

# Be polite: the API is free and we are not in a hurry.
REQUEST_DELAY_S = 0.2


@dataclass
class Article:
    title: str
    url: str
    revision_id: int
    text: str

    @property
    def doc_id(self) -> str:
        """Stable id: title plus revision, so two revisions never collide."""
        slug = self.title.replace(" ", "_")
        return f"wiki:{slug}@{self.revision_id}"


class WikipediaError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_article(
    title: str,
    *,
    session: requests.Session | None = None,
) -> Article | None:
    """Fetch one article as plain text at its *current* revision.

    Returns None if the article does not exist, so a typo in a seed list
    degrades to a warning rather than killing a long fetch.

    There is deliberately no `revision_id` parameter -- see the module
    docstring. The plaintext extract is only available for the current
    revision, so a historical revision cannot be re-fetched in this format.
    """
    s = session or _session()

    params = {
        "action": "query",
        "prop": "extracts|revisions",
        "titles": title,
        "explaintext": "1",
        "redirects": "1",
        "rvprop": "ids",
        "format": "json",
        "formatversion": "2",
    }

    resp = s.get(API, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    if "error" in payload:
        raise WikipediaError(payload["error"].get("info", "unknown API error"))

    pages = payload.get("query", {}).get("pages", [])
    if not pages:
        return None

    page = pages[0]
    if page.get("missing") or page.get("invalid"):
        return None

    text = page.get("extract", "") or ""
    if not text.strip():
        return None

    revisions = page.get("revisions") or []
    resolved_title = page.get("title", title)

    return Article(
        title=resolved_title,
        url=f"https://en.wikipedia.org/wiki/{resolved_title.replace(' ', '_')}",
        revision_id=revisions[0]["revid"] if revisions else -1,
        text=text,
    )


def fetch_articles(
    titles: list[str],
    *,
    on_progress=None,
) -> tuple[list[Article], list[str]]:
    """Fetch many articles. Returns (articles, failure descriptions)."""
    s = _session()
    got: list[Article] = []
    failed: list[str] = []

    for i, title in enumerate(titles, 1):
        try:
            art = fetch_article(title, session=s)
        except (requests.RequestException, WikipediaError) as exc:
            failed.append(f"{title}: {exc}")
        else:
            if art is None:
                failed.append(f"{title}: no such article")
            else:
                got.append(art)

        if on_progress:
            on_progress(i, len(titles), title)
        time.sleep(REQUEST_DELAY_S)

    return got, failed


def check_drift(
    manifest: dict[str, int],
    *,
    session: requests.Session | None = None,
    on_progress=None,
) -> list[tuple[str, int, int]]:
    """Compare pinned revisions against Wikipedia's current ones.

    Returns [(title, pinned_revision, current_revision)] for articles that have
    changed since the corpus was built. This is what the manifest is *for*: we
    cannot regenerate the old text, but we can always detect that it moved, so
    a stale index is a reported fact rather than a silent one.
    """
    s = session or _session()
    drifted: list[tuple[str, int, int]] = []

    for i, (title, pinned) in enumerate(manifest.items(), 1):
        try:
            art = fetch_article(title, session=s)
        except (requests.RequestException, WikipediaError):
            art = None
        if art is not None and art.revision_id != pinned:
            drifted.append((title, pinned, art.revision_id))

        if on_progress:
            on_progress(i, len(manifest), title)
        time.sleep(REQUEST_DELAY_S)

    return drifted


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def write_corpus(articles: list[Article], out_dir: Path) -> tuple[Path, Path]:
    """Write article text (gitignored) and the pinned manifest (committed)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    text_path = out_dir / "articles.jsonl"
    with text_path.open("w", encoding="utf-8") as fh:
        for art in articles:
            fh.write(
                json.dumps(
                    {
                        "doc_id": art.doc_id,
                        "title": art.title,
                        "url": art.url,
                        "revision_id": art.revision_id,
                        "text": art.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    manifest_path = out_dir / "manifest.json"
    manifest = {
        "source": "en.wikipedia.org",
        "fetched_count": len(articles),
        "articles": [
            {"title": a.title, "revision_id": a.revision_id, "url": a.url}
            for a in sorted(articles, key=lambda a: a.title)
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return text_path, manifest_path


def load_corpus(path: Path) -> list[Article]:
    """Read back a written corpus."""
    articles: list[Article] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            articles.append(
                Article(
                    title=rec["title"],
                    url=rec["url"],
                    revision_id=rec["revision_id"],
                    text=rec["text"],
                )
            )
    return articles


def load_manifest(path: Path) -> dict[str, int]:
    """Read a manifest into {title: revision_id} for pinned replay."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {a["title"]: a["revision_id"] for a in data.get("articles", [])}
