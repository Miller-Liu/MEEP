import asyncio

# Logger
import logging
from logging.handlers import RotatingFileHandler
from tools.logger import PrettyFormatter

from tools.gmail import Gmail
from tools.processor import Processor
# from tools.chatbot import ChatBot

import time
import os

stop_event = asyncio.Event()

async def gmail_fetch_loop(stop_event: asyncio.Event):
    """
    Continuously checks Gmail for new messages.
    Switches between IDLE and ACTIVE modes automatically.
    - IDLE mode: Checks less frequently.
    - ACTIVE mode: Fetches new emails and adds them to the sql database.
    """

    loop = asyncio.get_running_loop()
    state = "IDLE"
    last_activity = time.time()

    logger.info("[Gmail] Initialized gmail fetch loop.")

    try:
        while not stop_event.is_set():
            # Check Gmail inbox in a thread-safe way
            has_new = await loop.run_in_executor(None, gmail_client.check_inbox)

            # INACTIVE MODE
            if not has_new:
                # No new work for over one minute -> INACTIVE
                if state != "INACTIVE" and time.time() - last_activity > 1 * 60:
                    logger.info("[Gmail] No new messages for a while — switching to INACTIVE mode.")
                    state = "INACTIVE"
                await asyncio.sleep(5)
                continue

            # There is work → ACTIVE
            if has_new and state != "ACTIVE":
                logger.info("[Gmail] New messages detected — switching to ACTIVE mode.")
                state = "ACTIVE"
            
            # Do work here
            emails = gmail_client.get_unread_emails(10)
            await processor.add_emails_to_inbox(emails)
            last_activity = time.time()

            # Small delay to prevent tight loop
            await asyncio.sleep(0.5)
    except Exception as e:
        logger.exception(f"[Gmail] Unexpected error: {e}")

async def main():
    # set up necessary variables
    global chatbot, logger, gmail_client, processor
    log_path = os.path.join(os.getcwd(), "logs", "MEEP.log")

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
    gmail_client = Gmail(logger)

    # 
    processor = await Processor.create(logger)

    gmail_task = asyncio.create_task(gmail_fetch_loop(stop_event))
    processor_task = asyncio.create_task(processor.process_loop(stop_event, 10))
    try:
        await asyncio.gather(gmail_task, processor_task)
    except asyncio.CancelledError:
        stop_event.set()
        logger.info("[Main] Gmail loop cancelled — cleaning up.")
    except KeyboardInterrupt:
        stop_event.set()
        logger.info("[Main] KeyboardInterrupt detected — stopping gracefully.")
    except Exception:
        logger.exception("[Main] Exception:")
    finally:
        # ensure all async resources are properly closed
        await processor.terminate()
        logger.info("[Main] Shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())