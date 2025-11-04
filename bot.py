import feedparser
import telegram
import asyncio
import os
import logging
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
# Load secrets from environment variables for security
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Your Crunchyroll RSS feed
RSS_FEED_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"

# A file to store the IDs of posts we have already sent
SENT_POSTS_FILE = "sent_posts.txt"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- HELPER FUNCTIONS ---

def load_sent_posts():
    """Loads the set of already sent post IDs from a file."""
    if not os.path.exists(SENT_POSTS_FILE):
        return set()
    with open(SENT_POSTS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_sent_post(post_id):
    """Appends a new post ID to the file."""
    with open(SENT_POSTS_FILE, "a", encoding="utf-8") as f:
        f.write(str(post_id) + "\n")

def shorten_text(text, words=25):
    """Shortens text to a specific number of words."""
    if not text:
        return ""
    w = text.split()
    short = ' '.join(w[:words])
    return short + "..." if len(w) > words else short

def clean_description(description_html):
    """Cleans HTML from description and returns plain text."""
    if not description_html:
        return ""
    soup = BeautifulSoup(description_html, "html.parser")
    return soup.get_text().strip()

# --- MAIN LOGIC ---

async def check_and_send_news():
    """Checks the RSS feed for the latest entry and sends it to Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in environment variables.")
        return

    logging.info("Checking for the latest news...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    sent_posts = load_sent_posts()

    try:
        # Parse the RSS feed
        news_feed = feedparser.parse(RSS_FEED_URL)
        
        # Check if there are any entries in the feed
        if not news_feed.entries:
            logging.warning("No entries found in the RSS feed.")
            return

        # Get ONLY the first (latest) entry
        entry = news_feed.entries[0]
        post_id = entry.id
        logging.info(f"Latest post found: {entry.title}")

        # If we haven't sent this post yet, send it now
        if post_id not in sent_posts:
            
            # --- Get the image URL ---
            image_url = None
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0]['url']
                logging.info(f"Found image URL: {image_url}")

            # --- Get the clean, short description ---
            clean_desc = clean_description(entry.description)
            short_desc = shorten_text(clean_desc, words=25)
            
            # --- Prepare the message caption ---
            caption = f"*{entry.title}*\n\n{short_desc}"
            
            try:
                # --- Send the message ---
                if image_url:
                    # Send as a photo with a caption
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHAT_ID,
                        photo=image_url,
                        caption=caption,
                        parse_mode='Markdown'
                    )
                    logging.info(f"Successfully sent photo to Telegram: {entry.title}")
                else:
                    # If no image, send as a text message
                    await bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=caption,
                        parse_mode='Markdown'
                    )
                    logging.info(f"Successfully sent text message to Telegram: {entry.title}")
                
                # Save the ID so we don't send it again
                save_sent_post(post_id)
                
            except Exception as e:
                logging.error(f"Failed to send message to Telegram: {e}")
        else:
            logging.info(f"Latest post '{entry.title}' was already sent. Nothing to do.")

    except Exception as e:
        logging.error(f"Error parsing RSS feed: {e}")

    logging.info("Check complete.")


if __name__ == "__main__":
    asyncio.run(check_and_send_news())
