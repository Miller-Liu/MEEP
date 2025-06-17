import os
import json
import logging
from logging.handlers import RotatingFileHandler
from logger import PrettyFormatter
from notion_client import AsyncClient
import asyncio

class Database:
    def __init__(self, json_data : dict, logger : logging.Logger) -> None:
        self.logger = logger
        if "object" in json_data.keys() and json_data["object"] == "database":
            try:
                self.id = json_data["id"]
                self.name = json_data["title"][0]["plain_text"]
            except Exception as e:
                self.logger.error(f"[!] Failed with error: {e}")
        else:
            self.logger.error("[!] Not a database object")

    def __str__(self) -> str:
        return f"Database Name: {self.name}\nID: {self.id}"
    
    def __repr__(self) -> str:
        return f"\n{'-'*35}\n{str(self)}\n{'-'*35}"

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

    @classmethod
    async def create(cls):
        notion_obj = cls()
        await notion_obj.get_all_databases()
        print(notion_obj.databases)
        return notion_obj

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
    
    async def get_all_databases(self):
        client = await self.get_client()
        databases = []
        next_cursor = None

        if not client:
            self.logger.error(f"[!] Notion client doesn't exist")
            return

        while True:
            response = await client.search(
                filter={"property": "object", "value": "database"},
                start_cursor=next_cursor
            )
            databases.append(Database(response["results"][0], self.logger))
            next_cursor = response.get("next_cursor")
            if not response.get("has_more"):
                break

        self.databases = databases



async def main():
    obj = await Notion.create()

if __name__ == "__main__":
    asyncio.run(main())
