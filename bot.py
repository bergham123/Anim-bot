import requests
from bs4 import BeautifulSoup
import os
import logging
from PIL import Image
from io import BytesIO

# --- Config ---
# Load secrets from environment variables for security
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# These can stay here or also be moved to secrets
RSS_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"
SENT_FILE = "sent_posts.txt"
LOGO_PATH = "logo.png"
LOGO_MIN_WIDTH_RATIO = 0.10
LOGO_MAX_WIDTH_RATIO = 0.20
LOGO_MARGIN = 10

# --- Headers to bypass 403 ---
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

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# --- Load/Save sent posts ---
def load_sent_posts():
    # This function remains the same
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_post(title):
    # This function remains the same
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title + "\n")


# --- Shorten description ---
def shorten_text(text, words=20):
    # This function remains the same
    w = text.split()
    short = ' '.join(w[:words])
    return short + "..." if len(w) > words else short


# --- Add logo automatically resized (top-right) ---
def add_logo_to_image(image_url):
    # This function remains the same
    try:
        response = requests.get(image_url, headers=HEADERS)
        response.raise_for_status()
        post_image = Image.open(BytesIO(response.content)).convert("RGBA")
        logo = Image.open(LOGO_PATH).convert("RGBA")

        pw, ph = post_image.size

        lw = int(pw * LOGO_MIN_WIDTH_RATIO) if pw < 600 else int(pw * LOGO_MAX_WIDTH_RATIO)
        logo_ratio = lw / logo.width
        lh = int(logo.height * logo_ratio)
        logo = logo.resize((lw, lh), Image.LANCZOS)

        position = (pw - lw - LOGO_MARGIN, LOGO_MARGIN)
        post_image.paste(logo, position, logo)

        output = BytesIO()
        post_image.save(output, format="PNG")
        output.seek(0)
        return output
    except Exception as e:
        logging.error(f"Error adding logo: {e}")
        return None


# --- Fetch latest post ---
def get_latest_post():
    # This function remains the same
    try:
        response = requests.get(RSS_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        item = soup.find("item")
        if not item:
            logging.warning("No items found in RSS feed.")
            return None

        title = item.title.text.strip() if item.title else "بدون عنوان"

        description_tag = item.find("description")
        description_text = ""
        image_url = None
        if description_tag:
            desc_soup = BeautifulSoup(description_tag.text, "html.parser")
            img_tag = desc_soup.find("img")
            if img_tag:
                image_url = img_tag["src"]
                img_tag.extract()
            description_text = shorten_text(desc_soup.get_text().strip())

        if not image_url:
            media_thumb = item.find("media:thumbnail")
            if media_thumb and media_thumb.has_attr("url"):
                image_url = media_thumb["url"]

        return {
            "title": title,
            "image_url": image_url,
            "description": description_text
        }

    except Exception as e:
        logging.error(f"Error fetching RSS post: {e}")
        return None


# --- Send to Telegram ---
def send_post(title, image_url, description):
    # This function remains the same
    try:
        files = None
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": f"📰 <b>{title}</b>\n\n{description}",
            "parse_mode": "HTML"
        }

        if image_url:
            image_with_logo = add_logo_to_image(image_url)
            if image_with_logo:
                files = {"photo": ("image.png", image_with_logo)}
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                data = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"📰 <b>{title}</b>\n\n{description}",
                    "parse_mode": "HTML"
                }
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"📰 <b>{title}</b>\n\n{description}",
                "parse_mode": "HTML"
            }

        response = requests.post(url, data=data, files=files, timeout=10).json()
        if response.get("ok"):
            logging.info(f"Sent: {title}")
        else:
            logging.error(f"Telegram error: {response}")
    except Exception as e:
        logging.error(f"Error sending post: {e}")


# --- Main execution function (NO LOOP) ---
def main():
    logging.info("Starting bot run...")
    
    # Check if token and chat ID are set
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in environment variables.")
        return

    sent_posts = load_sent_posts()
    post = get_latest_post()

    if post and post["title"] not in sent_posts:
        logging.info(f"New post found: {post['title']}")
        send_post(post["title"], post["image_url"], post["description"])
        save_sent_post(post["title"])
        logging.info("Post sent and ID saved.")
    else:
        logging.info("No new post found or post was already sent.")

    logging.info("Bot run finished.")


if __name__ == "__main__":
    main()
