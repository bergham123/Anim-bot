import feedparser
import telegram
import asyncio
import os
import logging
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
import requests
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Crunchyroll
CRUNCHYROLL_RSS_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"
CRUNCHYROLL_SENT_FILE = "sent_posts.txt"

# YouTube
CHANNEL_ID = "UC1WGYjPeHHc_3nRXqbW3OcQ"
YOUTUBE_RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
YOUTUBE_SENT_FILE = "sent_videos.txt"

# Archive config (Africa/Casablanca day, <year>/<D-M>.json e.g. 2025/8-11.json)
ARCHIVE_TZ = ZoneInfo("Africa/Casablanca")
ARCHIVE_ROOT = "."

# Logo overlay
LOGO_PATH = "logo.png"
LOGO_MIN_WIDTH_RATIO = 0.10
LOGO_MAX_WIDTH_RATIO = 0.20
LOGO_MARGIN = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
    "Accept": "application/xml,application/xhtml+xml,text/html;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- Helpers ----------
def local_today():
    return datetime.now(ARCHIVE_TZ).date()

def to_local_date_from_utc(dt_utc):
    return dt_utc.astimezone(ARCHIVE_TZ).date()

def path_for_date(local_date):
    year_dir = os.path.join(ARCHIVE_ROOT, str(local_date.year))
    os.makedirs(year_dir, exist_ok=True)
    d_m = f"{local_date.day}-{local_date.month}"  # no leading zeros -> 8-11.json
    return os.path.join(year_dir, f"{d_m}.json")

def load_json(path, date_iso):
    if not os.path.exists(path):
        return {"date": date_iso, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load JSON {path}: {e}")
        return {"date": date_iso, "items": []}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Archived to {path}")
    except Exception as e:
        logging.error(f"Failed to write JSON {path}: {e}")

def today_archive_ids_for_source(source_name):
    """اقرأ ملف اليوم الموجود وخذ IDs الخاصة بالمصدر حتى لا نعيد الإرسال."""
    d = local_today()
    path = path_for_date(d)
    data = load_json(path, d.isoformat())
    ids = {it.get("id") for it in data.get("items", []) if it.get("source") == source_name}
    return ids

def archive_sent_item(item, dt_utc):
    """Append the sent item (only after successful Telegram send)."""
    local_date = to_local_date_from_utc(dt_utc)
    path = path_for_date(local_date)
    data = load_json(path, local_date.isoformat())
    existing = {it.get("id") for it in data["items"]}
    if item.get("id") not in existing:
        data["items"].append(item)
        data["items"].sort(key=lambda x: x.get("published_at", ""), reverse=True)
        save_json(path, data)
    else:
        logging.info("Item already archived for this day; skipping.")

def clean_text(html_or_text):
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "html.parser")
    return soup.get_text().strip()

def shorten_text(text, words=25):
    if not text:
        return ""
    w = text.split()
    short = " ".join(w[:words])
    return short + "..." if len(w) > words else short

def load_first_sent_post(sent_file):
    if not os.path.exists(sent_file):
        with open(sent_file, "w", encoding="utf-8"):
            pass
        return None
    try:
        with open(sent_file, "r", encoding="utf-8") as f:
            line = f.readline().strip()
            return line if line else None
    except Exception as e:
        logging.error(f"Error reading {sent_file}: {e}")
        return None

def save_sent_post(post_id, sent_file):
    try:
        prior = ""
        if os.path.exists(sent_file):
            with open(sent_file, "r", encoding="utf-8") as f:
                prior = f.read()
        with open(sent_file, "w", encoding="utf-8") as f:
            f.write(str(post_id) + "\n")
            if prior:
                f.write(prior)
    except Exception as e:
        logging.error(f"Error writing {sent_file}: {e}")

def add_logo_to_image(image_url):
    try:
        if not os.path.exists(LOGO_PATH):
            return None
        r = requests.get(image_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        post_image = Image.open(BytesIO(r.content)).convert("RGBA")
        logo = Image.open(LOGO_PATH).convert("RGBA")
        pw, ph = post_image.size
        lw = int(pw * (LOGO_MIN_WIDTH_RATIO if pw < 600 else LOGO_MAX_WIDTH_RATIO))
        logo = logo.resize((lw, int(logo.height * (lw / logo.width))), Image.LANCZOS)
        pos = (pw - logo.width - LOGO_MARGIN, LOGO_MARGIN)
        post_image.paste(logo, pos, logo)
        out = BytesIO()
        post_image.save(out, format="PNG")
        out.seek(0)
        return out
    except Exception as e:
        logging.error(f"Logo add failed: {e}")
        return None

def parse_entry_datetime(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)

# ---------- Core routine to send a list of items ----------
async def send_items(bot, items, sent_file, source_name):
    """
    يرسل كل العناصر غير المُرسَلة (حسب sent_file + JSON اليوم) بترتيب قديم -> جديد.
    كل عنصر يُؤرشف فقط بعد نجاح الإرسال.
    """
    # IDs الموجودة في JSON اليوم لهذا المصدر
    archived_ids_today = today_archive_ids_for_source(source_name)
    # ID الأحدث في ملف التتبع (نحافظ عليه كـ fallback قديم)
    first_sent = load_first_sent_post(sent_file)

    # فلترة العناصر غير المُرسلة
    def is_unsent(item):
        iid = str(item["id"])
        if iid in archived_ids_today:
            return False
        if first_sent and iid == str(first_sent):
            # هذا يطابق آخر ما أرسلناه تاريخياً كأحدث عنصر؛ لكن قد توجد عناصر أقدم غير مرسلة.
            # نعتمد على JSON اليوم لمنع التكرار، ونبقي هذا الشرط فقط كـ حماية عند بداية اليوم.
            return False
        return True

    unsent = [it for it in items if is_unsent(it)]

    # إرسال بالترتيب من الأقدم إلى الأحدث
    unsent.sort(key=lambda x: x["published_at"])

    for it in unsent:
        caption = it["caption"]
        try:
            if it.get("image_url"):
                img_with_logo = add_logo_to_image(it["image_url"])
                if img_with_logo:
                    await bot.send_photo(TELEGRAM_CHAT_ID, photo=img_with_logo, caption=caption, parse_mode="Markdown")
                else:
                    await bot.send_photo(TELEGRAM_CHAT_ID, photo=it["image_url"], caption=caption, parse_mode="Markdown")
            else:
                await bot.send_message(TELEGRAM_CHAT_ID, text=caption, parse_mode="Markdown")

            # بعد النجاح: حدّث ملف التتبع ليصبح آخر المُرسَل (الأحدث من حيث الـfeed سيأتي بالآخر)
            save_sent_post(it["id"], sent_file)

            # أرشف
            archive_sent_item(
                {
                    "id": str(it["id"]),
                    "source": source_name,
                    "title": it["title"],
                    "url": it["url"],
                    "image_url": it.get("image_url"),
                    "description_text": it["desc_text"],
                    "description_html": it["desc_html"],
                    "published_at": it["published_at"],
                    "lang": it.get("lang", "ar"),
                },
                datetime.fromisoformat(it["published_at"].replace("Z","+00:00")) if it["published_at"].endswith("Z") else datetime.fromisoformat(it["published_at"])
            )

        except Exception as e:
            logging.error(f"Failed to send {source_name} item: {e}")

# ---------- Crunchyroll ----------
async def check_and_send_crunchyroll_news(bot):
    logging.info("===== Checking Crunchyroll =====")
    try:
        feed = feedparser.parse(CRUNCHYROLL_RSS_URL)
        if not feed.entries:
            logging.warning("No Crunchyroll entries.")
            return

        today_local = local_today()
        items_today = []
        for entry in feed.entries:
            dt_utc = parse_entry_datetime(entry)
            if to_local_date_from_utc(dt_utc) != today_local:
                continue

            post_id = str(getattr(entry, "id", getattr(entry, "link", "")))
            title = entry.title
            url = getattr(entry, "link", None)
            desc_html = getattr(entry, "description", "")
            desc_text = clean_text(desc_html)

            image_url = None
            if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")
            if not image_url and desc_html:
                img = BeautifulSoup(desc_html, "html.parser").find("img")
                if img and img.has_attr("src"):
                    image_url = img["src"]

            caption = f"📰 *{title}*\n\n{shorten_text(desc_text, 25)}"

            items_today.append({
                "id": post_id,
                "title": title,
                "url": url,
                "image_url": image_url,
                "desc_text": desc_text,
                "desc_html": desc_html,
                "published_at": dt_utc.isoformat(),
                "caption": caption,
                "lang": "ar",
            })

        if not items_today:
            logging.info("No Crunchyroll items for today.")
            return

        await send_items(bot, items_today, CRUNCHYROLL_SENT_FILE, "crunchyroll")

    except Exception as e:
        logging.error(f"Crunchyroll feed error: {e}")

    logging.info("===== Done Crunchyroll =====")

# ---------- YouTube ----------
async def check_and_send_youtube_video(bot):
    logging.info("===== Checking YouTube =====")
    try:
        feed = feedparser.parse(YOUTUBE_RSS_URL)
        if not feed.entries:
            logging.warning("No YouTube entries.")
            return

        today_local = local_today()
        items_today = []
        for entry in feed.entries:
            dt_utc = parse_entry_datetime(entry)
            if to_local_date_from_utc(dt_utc) != today_local:
                continue

            video_id = str(getattr(entry, "yt_videoid", getattr(entry, "link", "")))
            title = entry.title
            url = getattr(entry, "link", None)
            thumb = entry.media_thumbnail[0]["url"] if hasattr(entry, "media_thumbnail") and entry.media_thumbnail else None
            desc_html = getattr(entry, "media_description", getattr(entry, "description", ""))
            desc_text = clean_text(desc_html)

            caption = f"🎬 *{title}*\n\n{shorten_text(desc_text, 25)}\n\n[Watch on YouTube]({url})"

            items_today.append({
                "id": video_id,
                "title": title,
                "url": url,
                "image_url": thumb,
                "desc_text": desc_text,
                "desc_html": desc_html,
                "published_at": dt_utc.isoformat(),
                "caption": caption,
                "lang": "ar",
            })

        if not items_today:
            logging.info("No YouTube items for today.")
            return

        await send_items(bot, items_today, YOUTUBE_SENT_FILE, "youtube")

    except Exception as e:
        logging.error(f"YouTube feed error: {e}")

    logging.info("===== Done YouTube =====")

# ---------- Main ----------
async def check_and_send_content():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set.")
        return
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    logging.info("===== Bot run start =====")
    await check_and_send_crunchyroll_news(bot)
    await check_and_send_youtube_video(bot)
    logging.info("===== Bot run end =====")

if __name__ == "__main__":
    asyncio.run(check_and_send_content())
s
