import feedparser
import telegram
import asyncio
import os
import logging

# --- CONFIGURATION ---
# Load secrets from environment variables for security
# I've used the same names as your previous script for consistency
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Your Crunchyroll RSS feed
RSS_FEED_URL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/ar-SA/rss"

# A file to store the IDs of posts we have already sent
SENT_POSTS_FILE = "sent_posts.txt"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- MAIN LOGIC ---

def load_sent_posts():
    """Loads the set of already sent post IDs from a file."""
    if not os.path.exists(SENT_POSTS_FILE):
        return set()
    with open(SENT_POSTS_FILE, "r", encoding="utf-8") as f:
        # Using a set for fast lookups
        return set(line.strip() for line in f)

def save_sent_post(post_id):
    """Appends a new post ID to the file."""
    with open(SENT_POSTS_FILE, "a", encoding="utf-8") as f:
        f.write(str(post_id) + "\n")

async def check_and_send_news():
    """Checks the RSS feed for new entries and sends them to Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("FATAL: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in environment variables.")
        return

    logging.info("Checking for news...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    sent_posts = load_sent_posts()

    try:
        # Parse the RSS feed
        news_feed = feedparser.parse(RSS_FEED_URL)
        
        # We check the latest 5 entries to avoid missing any
        for entry in news_feed.entries[:5]:
            post_id = entry.id  # Using the unique ID from the RSS feed

            # If we haven't sent this post yet, send it now
            if post_id not in sent_posts:
                logging.info(f"New post found: {entry.title}")
                
                # --- Get the image URL ---
                image_url = None
                # feedparser puts media thumbnails in entry.media_thumbnail
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url']
                    logging.info(f"Found image URL: {image_url}")

                # --- Prepare the message ---
                caption = f"*{entry.title}*\n\n[اقرأ المزيد]({entry.link})"
                
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
                    sent_posts.add(post_id)
                    
                    # Wait a moment between posts to avoid rate limits
                    await asyncio.sleep(3)
                except Exception as e:
                    logging.error(f"Failed to send message to Telegram: {e}")

    except Exception as e:
        logging.error(f"Error parsing RSS feed: {e}")

    logging.info("Check complete.")


if __name__ == "__main__":
    # This makes the script runnable
    asyncio.run(check_and_send_news())
