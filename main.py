import asyncio

# Logger
import logging
from logging.handlers import RotatingFileHandler
from tools.logger import PrettyFormatter


from tools.gmail import Gmail

import time
import os


root_dir = os.path.join(os.getcwd(), "logs")
log_path = os.path.join(root_dir, "MEEP_bot.log")

# Configure logger
logger = logging.getLogger("MEEP Bot")
logger.setLevel(logging.INFO)

# Configure writing to log files
handler = RotatingFileHandler(
    log_path,     			# path to log file
    maxBytes=5_000_000,     # 5 MB max file size
    backupCount=3           # Keep 3 old versions (log.1, log.2, log.3)
)

# Configure formatter for writing to log files
formatter = PrettyFormatter(datefmt='%Y-%m-%d %I:%M:%S %p')	# date log format
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.info("---------- Initialized logger object, script is running :) ----------")

# Configure gmail service
gmail_client = Gmail()

async def idle_mode():
    logger.info("[MODE] Switched to IDLE")
    loop = asyncio.get_running_loop()
    while True:
        has_new = await loop.run_in_executor(None, gmail_client.check_inbox, "UNREAD")
        if has_new:
            return "ACTIVE"
        await asyncio.sleep(30)

async def active_mode():
    logger.info("[MODE] Switched to ACTIVE")
    last_activity = time.time()
    async def fetch_new_messages():
        nonlocal last_activity
        loop = asyncio.get_running_loop()
        while True:
            has_new = await loop.run_in_executor(None, gmail_client.check_inbox, "UNREAD")
            if has_new:
                logger.info(f"[Active]: Fetching new messages")
                await loop.run_in_executor(None, gmail_client.process_inbox_emails, "UNREAD")
                last_activity = time.time()
            if time.time() - last_activity > 1 * 60:
                return "IDLE"
            await asyncio.sleep(2)

    async def process_next_message():
        nonlocal last_activity
        loop = asyncio.get_running_loop()
        while True:
            has_next = await loop.run_in_executor(None, gmail_client.check_email_queue)
            if has_next:
                logger.info(f"[Active]: Processing next message")
                email = await loop.run_in_executor(None, gmail_client.get_next_email)
                await loop.run_in_executor(None, gmail_client.reply_message, email, "seen this message")
                last_activity = time.time()
            if time.time() - last_activity > 1 * 60:
                return "IDLE"
    
    # Run both active tasks concurrently
    await asyncio.gather(fetch_new_messages(), process_next_message())


async def main():
    state = "IDLE"
    while True:
        if state == "IDLE":
            state = await idle_mode()
        elif state == "ACTIVE":
            state = await active_mode()

if __name__ == "__main__":
    asyncio.run(main())