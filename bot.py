# bot.py
import os
import json
import asyncio
import logging
import calendar
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import feedparser
from bs4 import BeautifulSoup

import requests
import telegram
from telegram import InputMediaPhoto

# ====================
# CONFIG
# ====================
TZ = ZoneInfo("Africa/Casablanca")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Sources
CRUNCHYROLL_RSS_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"

# YouTube
CHANNEL_ID       = "UC1WGYjPeHHc_3nRXqbW3OcQ"
YOUTUBE_RSS_URL  = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
YOUTUBE_SENT_FILE = Path("sent_videos.txt")

# Paths
DATA_BASE       = Path("data")                 # data/YYYY/MM/DD-MM.json
GLOBAL_INDEX    = Path("global_index")         # index_1.json, pagination.json, stats.json

# Global Index settings
GLOBAL_PAGE_SIZE = 500

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====================
# Utilities
# ====================
def now_local() -> datetime:
    return datetime.now(TZ)

def to_local_iso(dt_struct) -> str | None:
    """Convert feedparser *_parsed to ISO tz-aware Africa/Casablanca."""
    if not dt_struct:
        return None
    try:
        dt_utc = datetime.fromtimestamp(calendar.timegm(dt_struct), tz=timezone.utc)
        return dt_utc.astimezone(TZ).isoformat()
    except Exception:
        return None

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def daily_path(dt: datetime) -> Path:
    y, m, d = dt.year, dt.month, dt.day
    out_dir = DATA_BASE / f"{y}" / f"{m:02d}"
    ensure_dir(out_dir)
    return out_dir / f"{d:02d}-{m:02d}.json"   # example: data/2025/11/09-11.json

def load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logging.error(f"Failed reading {path}: {e}")
        return []

def save_json_list(path: Path, data: list):
    try:
        ensure_dir(path.parent)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed writing {path}: {e}")

def shorten_words(text: str, n=20) -> str:
    if not text:
        return ""
    w = text.split()
    return " ".join(w[:n])

# ====================
# RSS Field Extraction
# ====================
def extract_image(entry) -> str | None:
    # 1) media_thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        try:
            return entry.media_thumbnail[0].get("url") or entry.media_thumbnail[0]["url"]
        except Exception:
            pass
    # 2) find <img> in description
    html = getattr(entry, "description", None)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        if img and img.has_attr("src"):
            return img["src"]
    return None

def extract_categories(entry) -> list:
    cats = []
    tags = getattr(entry, "tags", None)
    if tags:
        for t in tags:
            term = getattr(t, "term", None)
            if term:
                cats.append(str(term))
    return cats

def extract_author(entry) -> str | None:
    if hasattr(entry, "author") and entry.author:
        return entry.author
    if hasattr(entry, "authors") and entry.authors:
        try:
            return entry.authors[0].get("name")
        except Exception:
            return None
    return None

def extract_language(feed) -> str | None:
    # Try feed-level language
    if hasattr(feed, "feed"):
        lang = feed.feed.get("language") or feed.feed.get("lang")
        return lang
    return None

def build_full_record(entry, feed_lang_default: str | None = None) -> dict:
    """Store ALL fields required inside the daily file."""
    rec_id = getattr(entry, "id", None) or getattr(entry, "link", None) or getattr(entry, "title", None)
    title  = getattr(entry, "title", "") or ""
    url    = getattr(entry, "link", "") or ""

    description_full = getattr(entry, "description", "") or ""   # HTML as-is
    image  = extract_image(entry)
    cats   = extract_categories(entry)
    published_iso = to_local_iso(getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None))
    author = extract_author(entry)
    language = getattr(entry, "language", None) or feed_lang_default or "ar-SA"

    return {
        "id": str(rec_id) if rec_id else None,
        "title": title,
        "description_full": description_full,
        "image": image,
        "categories": cats,
        "author": author,
        "published": published_iso,
        "language": language,
        "url": url
    }

# ====================
# Persist Daily News
# ====================
def save_full_news_of_today(entries, feed_meta=None):
    """
    - Build full records (all fields).
    - Append only NEW ones (by id, fallback url).
    - Return (added_records_list, path_str).
    """
    today = now_local()
    path = daily_path(today)
    existing = load_json_list(path)

    seen_ids  = { str(x.get("id"))  for x in existing if x.get("id") }
    seen_urls = { str(x.get("url")) for x in existing if x.get("url") }

    feed_lang_default = extract_language(feed_meta) if feed_meta else None

    added = []
    for e in entries:
        rec = build_full_record(e, feed_lang_default)
        rid = rec.get("id")
        rurl = rec.get("url")
        if (rid and str(rid) in seen_ids) or (rurl and str(rurl) in seen_urls):
            continue
        existing.append(rec)
        added.append(rec)
        if rid:  seen_ids.add(str(rid))
        if rurl: seen_urls.add(str(rurl))

    if added:
        save_json_list(path, existing)
    return added, str(path)

# ====================
# Manifests (month/year)
# ====================
def update_month_manifest(dt: datetime):
    y, m = dt.year, dt.month
    month_dir = DATA_BASE / f"{y}" / f"{m:02d}"
    ensure_dir(month_dir)
    manifest_path = month_dir / "month_manifest.json"

    # list all DD-MM.json files
    days = {}
    for p in sorted(month_dir.glob("*.json")):
        if p.name == "month_manifest.json":
            continue
        day_key = p.stem  # "DD-MM"
        days[day_key.split("-")[0]] = str(p.as_posix())

    manifest = {
        "year": str(y),
        "month": f"{m:02d}",
        "days": dict(sorted(days.items(), key=lambda kv: kv[0], reverse=True))
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def update_year_manifest(dt: datetime):
    y = dt.year
    year_dir = DATA_BASE / f"{y}"
    ensure_dir(year_dir)
    manifest_path = year_dir / "year_manifest.json"

    months = {}
    for p in sorted(year_dir.glob("[0-1][0-9]")):
        m = p.name
        months[m] = f"{(p / 'month_manifest.json').as_posix()}"

    manifest = {
        "year": str(y),
        "months": dict(sorted(months.items(), key=lambda kv: kv[0], reverse=True))
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

# ====================
# Global Index (search-friendly)
#   - Split files every 500 items: index_1.json, index_2.json, ...
#   - Each item: title, image, url, categories
#   - pagination.json: { total_articles, files: [...] }
#   - stats.json: { total_articles, added_today, last_update }
# ====================
def gi_paths():
    ensure_dir(GLOBAL_INDEX)
    pag_path  = GLOBAL_INDEX / "pagination.json"
    stats_path= GLOBAL_INDEX / "stats.json"
    return pag_path, stats_path

def gi_load_pagination():
    pag_path, _ = gi_paths()
    if not pag_path.exists():
        return {"total_articles": 0, "files": []}
    with open(pag_path, "r", encoding="utf-8") as f:
        return json.load(f)

def gi_save_pagination(pag):
    pag_path, _ = gi_paths()
    with open(pag_path, "w", encoding="utf-8") as f:
        json.dump(pag, f, ensure_ascii=False, indent=2)

def gi_save_stats(total_articles: int, added_today: int):
    _, stats_path = gi_paths()
    stats = {
        "total_articles": total_articles,
        "added_today": added_today,
        "last_update": now_local().isoformat()
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def gi_append_records(new_records: list):
    """
    Append slim records to the latest global_index/index_N.json
    Each record requires: title, image, url, categories
    """
    if not new_records:
        return

    pag = gi_load_pagination()

    # Determine current file
    if not pag["files"]:
        current_idx = 1
        current_file = GLOBAL_INDEX / f"index_{current_idx}.json"
        save_json_list(current_file, [])
        pag["files"].append(f"index_{current_idx}.json")
    else:
        current_file = GLOBAL_INDEX / pag["files"][-1]
        # in case missing on disk
        if not current_file.exists():
            save_json_list(current_file, [])

    # Load current page content
    items = load_json_list(current_file)

    # Rotate if needed
    if len(items) >= GLOBAL_PAGE_SIZE:
        next_idx = len(pag["files"]) + 1
        current_file = GLOBAL_INDEX / f"index_{next_idx}.json"
        save_json_list(current_file, [])
        pag["files"].append(f"index_{next_idx}.json")
        items = []

    # Append
    items.extend(new_records)
    save_json_list(current_file, items)

    # Save pagination + stats
    total = (pag.get("total_articles") or 0) + len(new_records)
    pag["total_articles"] = total
    gi_save_pagination(pag)
    gi_save_stats(total_articles=total, added_today=len(new_records))

def convert_full_to_slim(records: list) -> list:
    """
    Convert full records (daily saved) to slim records for global index.
    Keep: title, image, url, categories
    """
    out = []
    for r in records:
        out.append({
            "title": r.get("title"),
            "image": r.get("image"),
            "url": r.get("url"),
            "categories": r.get("categories") or []
        })
    return out

# ====================
# Telegram Senders
# ====================
async def send_crunchyroll_album(bot: telegram.Bot, new_records: list):
    """
    Send up to 4 NEW items as an album (title + image only), no links.
    If no images available, send one text message with titles only.
    """
    if not new_records:
        return

    # Sort by published (desc) if available, else as-is
    def keypub(r):
        try:
            return datetime.fromisoformat(r.get("published")) if r.get("published") else datetime.min.replace(tzinfo=TZ)
        except Exception:
            return datetime.min.replace(tzinfo=TZ)

    candidates = sorted(new_records, key=keypub, reverse=True)

    # Only items with images for the album
    photos = []
    for rec in candidates:
        if rec.get("image"):
            caption = rec.get("title") or ""
            photos.append(InputMediaPhoto(media=rec["image"], caption=caption))
        if len(photos) >= 4:
            break

    # If we have photos, send as one media group (single message album)
    if photos:
        try:
            await bot.send_media_group(chat_id=TELEGRAM_CHAT_ID, media=photos)
            return
        except Exception as e:
            logging.error(f"send_media_group failed: {e}")

    # Fallback: send a compact text list (no links)
    lines = []
    for rec in candidates[:4]:
        lines.append(f"• {rec.get('title')}")
    if lines:
        text = "📰 أحدث أخبار الأنمي من Crunchyroll\n\n" + "\n".join(lines)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)

async def send_youtube_if_new(bot: telegram.Bot):
    """
    Send latest YouTube video if it's new.
    - Not stored in data/
    - ID saved to sent_videos.txt (top line)
    """
    feed = feedparser.parse(YOUTUBE_RSS_URL)
    if not feed.entries:
        return

    entry = feed.entries[0]
    vid = getattr(entry, "yt_videoid", None) or getattr(entry, "id", None)
    title = getattr(entry, "title", "")
    url   = getattr(entry, "link", "")
    thumb = None
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        thumb = entry.media_thumbnail[0].get("url")

    # read first line of sent_videos
    if not YOUTUBE_SENT_FILE.exists():
        YOUTUBE_SENT_FILE.write_text("", encoding="utf-8")
        last = None
    else:
        with open(YOUTUBE_SENT_FILE, "r", encoding="utf-8") as f:
            last = f.readline().strip() or None

    # already sent?
    if last and vid and vid == last:
        return

    # send
    caption = f"🎥 {title}\nشاهد على يوتيوب:\n{url}"
    try:
        if thumb:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=thumb, caption=caption)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption)
    except Exception as e:
        logging.error(f"Failed to send YouTube: {e}")
        return

    # persist id (prepend)
    try:
        old = ""
        if YOUTUBE_SENT_FILE.exists():
            old = YOUTUBE_SENT_FILE.read_text(encoding="utf-8")
        with open(YOUTUBE_SENT_FILE, "w", encoding="utf-8") as f:
            f.write((vid or "") + "\n")
            if old:
                f.write(old)
    except Exception as e:
        logging.error(f"Failed updating {YOUTUBE_SENT_FILE}: {e}")

# ====================
# Main Routine
# ====================
async def run():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set.")
        return

    bot = telegram.Bot(token=TELEGRAM_TOKEN)

    # 1) Fetch Crunchyroll
    news_feed = feedparser.parse(CRUNCHYROLL_RSS_URL)
    if news_feed.entries:
        # Save full records of TODAY (all fields)
        added_records, day_path = save_full_news_of_today(news_feed.entries, feed_meta=news_feed)
        logging.info(f"Crun: added {len(added_records)} new record(s) to {day_path}")

        # Send album (latest up to 4 new items) – title + image only (no links)
        await send_crunchyroll_album(bot, added_records)

        # Update manifests for month / year
        today = now_local()
        update_month_manifest(today)
        update_year_manifest(today)

        # Update global index (slim: title, image, url, categories) with pagination
        slim = convert_full_to_slim(added_records)
        gi_append_records(slim)

    else:
        logging.warning("No entries in Crunchyroll feed.")

    # 2) YouTube (send if new; no data/ persistence)
    await send_youtube_if_new(bot)

if __name__ == "__main__":
    asyncio.run(run())
