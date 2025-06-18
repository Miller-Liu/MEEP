import os
import json
import logging
from logging.handlers import RotatingFileHandler
from logger import PrettyFormatter
from notion_client import AsyncClient
import asyncio
import traceback

# helper class for keeping track and safety checking information about the databases
class Databases:
    def __init__(self, logger : logging.Logger) -> None:
        self.logger = logger
        self.databases = {}

        # configure self.lookup: used to find what properties are required and optional
        root_dir = os.path.join(os.getcwd(), "tools")
        database_config = os.path.join(root_dir, "notion_config.json")
        with open(database_config, "r") as f:
            self.lookup = json.load(f)

    # configure self.databases: maps property names to their important fields
    def add_database(self, json_data : dict) -> None:
        if "object" in json_data.keys() and json_data["object"] == "database":
            try:
                id = json_data["id"]
                name = json_data["title"][0]["plain_text"]
                properties = {}
                # get the property names and values from the json dictionary data
                for prop_name, prop_value in json_data["properties"].items():
                    # only add the property fields we care about
                    if prop_name in self.lookup[name]["required"] or prop_name in self.lookup[name]["optional"].keys():
                        properties[prop_name.lower()] = {"name": prop_name, "id": prop_value["id"], "type": prop_value["type"]}
                        if prop_value["type"] in ["select", "status", "multi_select"]:
                            properties[prop_name.lower()]["options"] = {option["name"].lower(): option["name"] for option in prop_value[prop_value["type"]]["options"]}
                self.databases[name.lower()] = {"name": name, "id": id, "properties": properties}
            except Exception:
                self.logger.error(f"[!] Failed to add database:\n{traceback.format_exc()}")
        else:
            self.logger.error("[!] Not a database object")
    
    # Check if arguments are valid for database (arguments = {lowercase string : value})
    #   return -> code, message (where 0 = failure and 1 = success)
    def is_valid_page(self, database : str, arguments : dict):
        database = database.lower()
        # check: database is a valid entry
        if database not in self.databases.keys():
            self.logger.error(f"[!] {database} is not a valid database endpoint")
            return 0, f"{database} is not a valid database endpoint"
        
        # check: given properties are valid
        for name in arguments.keys():
            name = name.lower()
            if name not in self.databases[database]["properties"].keys():
                self.logger.error(f"[!] {name} is not a valid property")
                return 0, f"{name} is not a valid property"
        
        # check: all required arguments are present
        for required_arg in self.lookup[self.databases[database]["name"]]["required"]:
            if required_arg.lower() not in arguments.keys():
                self.logger.error(f"[!] Required argument -- {required_arg} -- is not given")
                return 0, f"Required argument -- {required_arg} -- is not given"
            
        # we know the page is valid, format page json to return
        page = {}
        page["parent"] = {
            "type": "database_id",
            "database_id": self.databases[database]["id"]
        }
        # set up properties
        page["properties"] = {}
        for arg, value in arguments.items():
            prop_name = self.databases[database]["properties"][arg.lower()]["name"]
            prop_id = self.databases[database]["properties"][arg.lower()]["id"]
            prop_type = self.databases[database]["properties"][arg.lower()]["type"]
            # assigning property value based on property type
            if prop_type == "number":
                if type(value) == int or type(value) == float:
                    prop_value = value
                else:
                    return 0, f"{arg} is type {type(value)} and not integer or float"
            elif prop_type in ["title", "rich_text"]:
                if type(value) == str:
                    prop_value = [{"type": "text", "text": {"content": value}}]
                else:
                    return 0, f"{arg} is type {type(value)} and not string"
            elif prop_type in ["select", "status"]:
                value = value.lower()
                if value in self.databases[database]["properties"][arg.lower()]["options"].keys():
                    prop_value = {"name": self.databases[database]["properties"][arg.lower()]["options"][value]}
                else:
                    return 0, f"{arg} is not a valid option"
            else:
                return 0, f"Invalid property type: {prop_type}"
            page["properties"][prop_name] = {
                "id": prop_id,
                prop_type: prop_value
            }
        return 1, page

    def __str__(self) -> str:
        return_str = ""
        for name in self.databases.keys():
            return_str += f"{name}: {json.dumps(self.databases[name], indent=4)}\n"
        return return_str

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

    # async initialization of Notion object
    @classmethod
    async def create(cls):
        notion_obj = cls()
        await notion_obj.get_all_databases()
        return notion_obj

    # construct Notion API client
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
                    return None
        self.logger.error(f"[!] notion_api.json is an invalid path")
        return None
    
    # retrieve all databases our API has access to
    async def get_all_databases(self):
        client = await self.get_client()
        databases = Databases(self.logger)
        next_cursor = None

        if not client:
            self.logger.error(f"[!] Notion client doesn't exist")
            return

        while True:
            response = await client.search(
                filter={"property": "object", "value": "database"},
                start_cursor=next_cursor
            )
            for database in response["results"]:
                databases.add_database(database)
            # if this page doesn't contain everything
            next_cursor = response.get("next_cursor")
            if not response.get("has_more"):
                break

        self.databases = databases
        self.logger.info(f"[✓] List of databases: \n{self.databases}")

    async def add_page_to_database(self, database, properties : dict):
        # lower all keys in input
        properties = {k.lower(): v for k, v in properties.items()}
        code, msg = self.databases.is_valid_page(database, properties)
        if code == 1: # success
            client = await self.get_client()
            if client:
                response = await client.pages.create(**msg) # type: ignore
            else:
                self.logger.error(f"[!] Adding page to {database} failed")
                return 0, f"Adding page to {database} failed"
        return code, msg



async def main():
    obj = await Notion.create()
    props = {"nAMe":"testing1", "seLect":"option1", "status":"Done"}
    print(await obj.add_page_to_database("testing", props))


if __name__ == "__main__":
    asyncio.run(main())
