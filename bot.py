import requests
from bs4 import BeautifulSoup
import os
import logging

# --- Config ---
# Load secrets from environment variables for security
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# RSS Feed URL
RSS_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"
SENT_FILE = "sent_posts.txt"

# --- Headers to bypass 403 ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# --- Load/Save sent posts ---
def load_sent_posts():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_post(title):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(title + "\n")


# --- Fetch latest post ---
def get_latest_post():
    logging.info(f"Fetching RSS feed from: {RSS_URL}")
    try:
        response = requests.get(RSS_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        item = soup.find("item")
        if not item:
            logging.warning("No items found in RSS feed.")
            return None

        title = item.title.text.strip() if item.title else "بدون عنوان"
        link = item.link.text.strip() if item.link else "#"
        
        logging.info(f"Found latest post: '{title}'")
        return {
            "title": title,
            "link": link
        }

    except Exception as e:
        logging.error(f"Error fetching or parsing RSS feed: {e}")
        return None


# --- Send to Telegram ---
def send_post(title, link):
    logging.info("Attempting to send post to Telegram...")
    try:
        # Create a simple text message with a link
        message_text = f"📰 <b>{title}</b>\n\n[اقرأ المزيد]({link})"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false" # Show the link preview
        }
        
        response = requests.post(url, json=payload, timeout=15).json()
        
        if response.get("ok"):
            logging.info(f"Successfully sent to Telegram: {title}")
            return True
        else:
            logging.error(f"Telegram API error: {response}")
            return False
            
    except Exception as e:
        logging.error(f"Error sending post to Telegram: {e}")
        return False


# --- Main execution function ---
def main():
    logging.info("="*20)
    logging.info("Starting a new bot run...")
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in environment variables.")
        return

    sent_posts = load_sent_posts()
    post = get_latest_post()

    if post:
        if post["title"] not in sent_posts:
            logging.info(f"New post detected: '{post['title']}'")
            success = send_post(post["title"], post["link"])
            if success:
                save_sent_post(post["title"])
                logging.info("Post sent and title saved for future reference.")
        else:
            logging.info(f"Post '{post['title']}' already sent. Nothing to do.")
    else:
        logging.warning("Could not retrieve the latest post from the feed.")

    logging.info("Bot run finished.")
    logging.info("="*20)


if __name__ == "__main__":
    main()
