import feedparser
import telegram
import asyncio
import os
import time

# --- CONFIGURATION ---
# We will load these from environment variables for security
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
RSS_FEED_URL = "https://www.animenewsnetwork.com/news/rss.xml"

# A file to store the IDs of posts we have already sent
SENT_POSTS_FILE = "sent_posts.txt"

# --- MAIN LOGIC ---

def load_sent_posts():
    """Loads the set of already sent post IDs from a file."""
    if not os.path.exists(SENT_POSTS_FILE):
        return set()
    with open(SENT_POSTS_FILE, "r") as f:
        # Using a set for fast lookups
        return set(line.strip() for line in f)

def save_sent_post(post_id):
    """Appends a new post ID to the file."""
    with open(SENT_POSTS_FILE, "a") as f:
        f.write(str(post_id) + "\n")

async def check_and_send_news():
    """Checks the RSS feed for new entries and sends them to Telegram."""
    if not BOT_TOKEN or not CHANNEL_ID:
        print("Error: BOT_TOKEN or CHANNEL_ID not set in environment variables.")
        return

    print("Checking for news...")
    bot = telegram.Bot(token=BOT_TOKEN)
    sent_posts = load_sent_posts()

    try:
        # Parse the RSS feed
        news_feed = feedparser.parse(RSS_FEED_URL)
        
        # We check the latest 5 entries to avoid missing any
        for entry in news_feed.entries[:5]:
            post_id = entry.id  # Using the unique ID from the RSS feed

            # If we haven't sent this post yet, send it now
            if post_id not in sent_posts:
                print(f"New post found: {entry.title}")
                
                # Format the message for Telegram
                # Using Markdown for a nice link format
                message = f"*{entry.title}*\n\n[Read more]({entry.link})"
                
                try:
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=message,
                        parse_mode='Markdown'
                    )
                    print(f"Successfully sent to Telegram: {entry.title}")
                    
                    # Save the ID so we don't send it again
                    save_sent_post(post_id)
                    sent_posts.add(post_id) # Add to our current set too
                    
                    # Wait a moment between posts to avoid rate limits
                    await asyncio.sleep(3)
                except Exception as e:
                    print(f"Failed to send message to Telegram: {e}")

    except Exception as e:
        print(f"Error parsing RSS feed: {e}")

    print("Check complete.")


if __name__ == "__main__":
    # This makes the script runnable
    asyncio.run(check_and_send_news())
