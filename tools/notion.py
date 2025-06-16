import os
import json
import logging
from logging.handlers import RotatingFileHandler
from logger import PrettyFormatter
from notion_client import AsyncClient
import asyncio

class Filter:
    def __init__(self) -> None:
        pass

class Notion:
    def __init__(self) -> None:
        root_dir = os.path.join(os.getcwd(), "logs")
        log_path = os.path.join(root_dir, "notion_bot.log")

        # Configure logger
        self.logger = logging.getLogger("MEEP Gmail Bot")
        self.logger.setLevel(logging.INFO)

        # Configure writing to log files
        handler = RotatingFileHandler(
            log_path,     			# path to log file
            maxBytes=5_000_000,     # 5 MB max file size
            backupCount=3           # Keep 3 old versions (log.1, log.2, log.3)
        )

        # Configure formatter for writing to log files
        formatter = PrettyFormatter(datefmt='%Y-%m-%d %I:%M:%S %p')	# date log format
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.info("---------- Initialized logger object, script is running :) ----------")

    async def get_client(self):
        """
        Set up and return client 
        """
        root_dir = os.path.join(os.getcwd(), "tools")
        key_path = os.path.join(root_dir, "notion_api.json")

        # Load gmail_token.json if it exists
        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                try:
                    api_key = json.load(f)["NOTION_KEY"]
                    client = AsyncClient(auth=api_key)
                    self.logger.info("[✓] Notion client created")
                    return client
                except Exception as e:
                    self.logger.error(f"[!] Failed to parse notion_api.json: {e}")
        self.logger.error(f"[!] notion_api.json is an invalid path")
        return None
    
    async def get_all_pages(self):
        client = await self.get_client()
        pages = []
        next_cursor = None

        if not client:
            self.logger.error(f"[!] Notion client doesn't exist")
            return

        while True:
            response = await client.search(
                filter={"property": "object", "value": "database"},
                start_cursor=next_cursor
            )
            pages.extend(response["results"])
            next_cursor = response.get("next_cursor")
            if not response.get("has_more"):
                break

        return pages



async def main():
    obj = Notion()
    pages = await obj.get_all_pages()
    print(pages)

if __name__ == "__main__":
    asyncio.run(main())
