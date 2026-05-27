#!/usr/bin/env python3
"""Fetch RSS feeds, filter recent articles, and generate a markdown summary."""

import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import ssl
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

TODAY = datetime.now(timezone.utc)
DATE_STR = TODAY.strftime("%Y-%m-%d")

FEEDS = [
    ("Nielsen Norman Group", "https://www.nngroup.com/feed/rss/"),
    ("UX Design (Medium)", "https://uxdesign.cc/feed"),
    ("UX Planet", "https://uxplanet.org/feed"),
    ("Smashing Magazine", "https://www.smashingmagazine.com/feed/"),
    ("A List Apart", "https://alistapart.com/main/feed/"),
    ("UX Booth", "https://www.uxbooth.com/articles/feed/"),
    ("UX Matters", "https://www.uxmatters.com/index.xml"),
    ("Boxes and Arrows", "https://boxesandarrows.com/rss/"),
    ("Mind the Product", "https://www.mindtheproduct.com/feed/"),
    ("Product Coalition", "https://productcoalition.com/feed"),
    ("Lenny's Newsletter", "https://www.lennysnewsletter.com/feed"),
    ("Practical Service Design", "https://www.practicalservicedesign.com/feed"),
    ("Service Design Show", "https://servicedesignshow.com/feed/"),
    ("Towards Data Science", "https://towardsdatascience.com/feed"),
    ("Behavioral Economics", "https://www.behavioraleconomics.com/feed/"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("Wired Design", "https://www.wired.com/feed/category/design/latest/rss"),
    ("Fast Company Design", "https://www.fastcompany.com/section/design/rss"),
    ("The Verge Design", "https://www.theverge.com/design/rss/index.xml"),
    ("Hacker News UX/Design", "https://hnrss.org/newest?q=UX+design+product&count=30"),
    ("Hacker News AI/Design", "https://hnrss.org/newest?q=AI+design+research&count=20"),
]

TOPIC_KEYWORDS = [
    "ux", "ui", "user experience", "user interface", "interaction design",
    "design system", "design systems", "component", "accessibility",
    "user research", "usability", "usability testing", "interview", "survey",
    "product design", "product management", "product strategy", "roadmap",
    "service design", "customer experience", "cx", "journey map",
    "behavioral", "behaviour", "cognitive", "mental model", "nudge",
    "data", "analytics", "metrics", "kpi", "a/b test",
    "ai", "artificial intelligence", "machine learning", "llm", "gpt",
    "chatgpt", "generative", "automation", "copilot",
    "trend", "future", "innovation", "strategy",
    "design leadership", "design manager", "design ops", "designops",
    "figma", "prototype", "wireframe", "information architecture",
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
}


def fetch_feed(url: str) -> bytes | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; RSS-Curator/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read()
    except Exception as e:
        print(f"  [skip] {url}: {e}", file=sys.stderr)
        return None


def parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    date_str = date_str.strip()
    # Try RFC 2822 (RSS pubDate)
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # Try ISO 8601 / Atom
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:len(fmt)+5], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    # Fallback: grab first date-like substring
    m = re.search(r"\d{4}-\d{2}-\d{2}", date_str)
    if m:
        try:
            dt = datetime.strptime(m.group(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def text(el) -> str:
    if el is None:
        return ""
    t = el.text or ""
    # strip HTML tags
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_articles_rss(root) -> list[dict]:
    articles = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate") or item.find("dc:date", NS)

        title = text(title_el)
        link = (link_el.text or "").strip() if link_el is not None else ""
        description = text(desc_el)
        pub_date = parse_date(text(date_el) if date_el is not None else None)

        if title and link:
            articles.append({
                "title": title,
                "link": link,
                "description": description,
                "date": pub_date,
            })
    return articles


def extract_articles_atom(root) -> list[dict]:
    articles = []
    for entry in root.findall("atom:entry", NS):
        title_el = entry.find("atom:title", NS)
        link_el = entry.find("atom:link", NS)
        summary_el = entry.find("atom:summary", NS) or entry.find("atom:content", NS)
        date_el = entry.find("atom:published", NS) or entry.find("atom:updated", NS)

        title = text(title_el)
        link = ""
        if link_el is not None:
            link = link_el.get("href", "") or (link_el.text or "")
        description = text(summary_el)
        pub_date = parse_date(text(date_el) if date_el is not None else None)

        if title and link:
            articles.append({
                "title": title,
                "link": link,
                "description": description,
                "date": pub_date,
            })
    return articles


def parse_feed(data: bytes) -> list[dict]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        # Try stripping BOM or bad chars
        try:
            cleaned = data.decode("utf-8", errors="replace").lstrip("﻿")
            root = ET.fromstring(cleaned.encode("utf-8"))
        except Exception:
            return []

    tag = root.tag.lower()
    if "feed" in tag or "atom" in tag:
        return extract_articles_atom(root)
    # RSS 2.0 / RSS 1.0
    return extract_articles_rss(root)


def is_relevant(article: dict) -> bool:
    combined = (article["title"] + " " + article["description"]).lower()
    return any(kw in combined for kw in TOPIC_KEYWORDS)


def filter_by_window(articles: list[dict], hours: int) -> list[dict]:
    cutoff = TODAY - timedelta(hours=hours)
    return [a for a in articles if a["date"] and a["date"] >= cutoff]


def truncate(text: str, max_chars: int = 600) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def main():
    all_selected: list[tuple[str, dict]] = []  # (feed_name, article)

    for feed_name, url in FEEDS:
        print(f"Fetching: {feed_name}", file=sys.stderr)
        data = fetch_feed(url)
        if not data:
            continue

        articles = parse_feed(data)
        if not articles:
            print(f"  [empty] no articles parsed", file=sys.stderr)
            continue

        # Try 24h window first
        recent = filter_by_window(articles, 24)
        window = 24
        if len(recent) < 5:
            recent = filter_by_window(articles, 48)
            window = 48

        if not recent:
            # No articles in 48h — take the 3 most recent regardless (fallback)
            dated = [a for a in articles if a["date"]]
            dated.sort(key=lambda a: a["date"], reverse=True)
            recent = dated[:3]
            window = 0

        relevant = [a for a in recent if is_relevant(a)]
        if not relevant:
            relevant = recent  # Fallback: keep all recent even without keyword match

        # Sort by date descending, cap at 3 per feed
        relevant.sort(key=lambda a: a["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        relevant = relevant[:3]

        print(f"  → {len(relevant)} article(s) selected (window={window}h)", file=sys.stderr)
        for a in relevant:
            all_selected.append((feed_name, a))

    # Build markdown
    os.makedirs("resumos", exist_ok=True)
    out_path = f"resumos/{DATE_STR}.md"

    lines = [
        f"# Curadoria de Design, UX & Produto — {DATE_STR}",
        "",
        f"> Gerado em {TODAY.strftime('%Y-%m-%d %H:%M UTC')} | {len(all_selected)} artigos selecionados",
        "",
        "---",
        "",
    ]

    # Group by feed
    seen_feeds: dict[str, list[tuple[str, dict]]] = {}
    for feed_name, article in all_selected:
        seen_feeds.setdefault(feed_name, []).append((feed_name, article))

    for feed_name, items in seen_feeds.items():
        lines.append(f"## {feed_name}")
        lines.append("")
        for _, article in items:
            date_str = article["date"].strftime("%d/%m/%Y %H:%M UTC") if article["date"] else "data desconhecida"
            desc = truncate(article["description"]) if article["description"] else "_Sem descrição disponível._"
            lines.append(f"### {article['title']}")
            lines.append("")
            lines.append(f"**Feed:** {feed_name}  ")
            lines.append(f"**Link:** {article['link']}  ")
            lines.append(f"**Publicado:** {date_str}")
            lines.append("")
            lines.append(f"{desc}")
            lines.append("")
            lines.append("---")
            lines.append("")

    content = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\nArquivo gerado: {out_path} ({len(all_selected)} artigos)")


if __name__ == "__main__":
    main()
