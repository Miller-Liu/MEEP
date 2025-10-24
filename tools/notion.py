import os
import sys
import json
import asyncio
import aiohttp
from types import SimpleNamespace
from fuzzywuzzy import process

class NotionException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
    
    def __str__(self) -> str:
        return f"[!] Notion Exception: {self.args[0]}"

def exception_handler(exception_type, exception, traceback):
    # All your trace are belong to us!
    print(exception)


class NotionClient:
    def __init__(self, api_key : str) -> None:
        self._client = aiohttp.ClientSession(
            base_url="https://api.notion.com/v1/",
            headers={
                "Authorization": f"Bearer {api_key}", # type: ignore
                "Notion-Version": "2025-09-03",
                "Content-Type": "application/json"
            }
        )

        # datasource endpoints
        self.datasources = SimpleNamespace(
            get = lambda id: self.get(f"data_sources/{id}")
        )

        self.pages = SimpleNamespace(
            create = lambda page: self.post(f"pages", page)
        )

    async def get(self, url : str):
        resp = await self._client.get(url)

        if resp.status == 200:
            return json.loads(await resp.text())
    
    async def post(self, url : str, data = None):
        resp = await self._client.post(url, json=data)

        if resp.status == 200:
            return json.loads(await resp.text())

    async def close(self):
        await self._client.close()

class Datasource:
    def __init__(self, name : str, configs: dict, api_key : str) -> None:

        # Important fields
        self.name = name
        self.description = ""
        self._id = ""
        self._api_key = api_key
        self._properties = {}

        # Create Async Notion API client
        self._client = NotionClient(api_key)

        # Initializes
        #   lookup: maps inputs to corresponding properties
        #   properties: map properties to empty dict
        # Note: property names are lowered in lookup to allow for lenient input 
        try:
            self._id = configs["id"]
            for _, props in configs["commands"].items():
                for req_prop_name in props["required"]:
                    self._properties[req_prop_name] = {}
                for _, opt_prop_name in props["optional"].items():
                    self._properties[opt_prop_name] = {}
        except:
            raise NotionException(f"Invalid commands configuration for datasource: [{name}]")

    @classmethod
    async def create(cls, name : str, config: dict, api_key : str) -> 'Datasource':
        datasource_obj = cls(name, config, api_key)
        
        # Get datasource information
        resp = await datasource_obj._client.datasources.get(datasource_obj._id)

        # Get datasource description
        for chunk in resp["description"]:
            if chunk["type"] == "text":
                datasource_obj.description += chunk["plain_text"] + " "

        # Get datasource properties
        for prop_name, prop_value in resp["properties"].items():
            if prop_name in datasource_obj._properties:
                # set up current property according to the type
                curr_property = {
                    "id": prop_value["id"],
                    "type": prop_value["type"]
                }
                match prop_value["type"]:
                    case "title":
                        pass
                    case "select":
                        curr_property["options"] = {}
                        for option in prop_value["select"]["options"]:
                            curr_property["options"][option["name"]] = option["id"]
                    case _:
                        raise NotionException(f"[{datasource_obj.name}]'s property type {prop_value['type']} is unsupported.")
                
                datasource_obj._properties[prop_name] = curr_property

        # Checks all properties in config are valid
        for prop_name, prop_value in datasource_obj._properties.items():
            if not prop_value:
                raise NotionException(f"Datasource [{datasource_obj.name}]'s property [{prop_name}] is not found.")
        
        return datasource_obj
        
    # async def get_page(self, )
    
    # async def edit_page(self, page_id, properties : dict):
    #     for prop, value in properties:

    # assumes arguments are valid (property names and values are correct)
    async def add_page(self, arguments : dict) -> str:
        # Create page object
        page = {}
        page["parent"] = {
            "type": "data_source_id",
            "data_source_id": self._id
        }
        page["properties"] = {}

        # Name: 
        for arg, value in arguments.items():
            # Get property information
            prop_id = self._properties[arg]["id"]
            prop_type = self._properties[arg]["type"]

            prop = self.format_property(arg, value)
            if not prop:
                return "Properties are incorrectly formatted."

            page["properties"][arg] = {
                "id": prop_id,
                "type": prop_type,
                prop_type: prop, 
            }
        
        response = await self._client.pages.create(page)
        if not response: # creation failed
            return "Error: Creating page encountered unexpected error."
        if response["object"] == "error":
            return "Error: " + response["message"]

        return "Success"

    def format_property(self, prop_name, prop_value):
        '''Returns formatted property, returns null equivalent value if property value is invalid'''
        match self._properties[prop_name]["type"]:
            # note that inputs for properties are divided by \n most likely so no multiline inputs
            case "title" | "rich_text":
                return [{
                    "type": "text", 
                    "text": {
                        "content": prop_value
                    },
                    "plain_text": prop_value
                }]

            case "select":
                matched_option = process.extractOne(prop_value, self._properties[prop_name]["options"].keys())
                if matched_option[1] < 80: # type: ignore
                    print("Invalid option", prop_value)
                    return {}
                return { "name": matched_option[0] } # type: ignore
            
            case "multi_select":
                prop = []
                for value in prop_value:
                    matched_option = process.extractOne(value, self._properties[prop_name]["options"])
                    if matched_option[1] < 80: # type: ignore
                        print("Invalid option", value)
                        return {}
                    prop.append({ "name": matched_option[0] }) # type: ignore
                return prop

    def property_help(self, indent : int) -> str:
        '''Help function printing out information about valid property inputs'''
        return_str = ""
        for prop_name, prop_values in self._properties.items():
            return_str += " " * indent + prop_name + ": " + prop_values["type"] + "\n"

            match prop_values["type"]:
                case "select":
                    for option_name in prop_values["options"].keys():
                        return_str += " " * (indent * 2) + option_name + "\n"

        return return_str
    
    async def terminate(self):
        await self._client.close()
    
    def __str__(self) -> str:
        return json.dumps({"name": self.name, "id": self._id, "properties": self._properties}, indent=4)

    def __bool__(self):
        return bool(self._id)
    

class Notion:
    def __init__(self) -> None:
        '''Set up Notion object according to configuration file'''

        # Important fields
        self._api_key = ""
        self._blocks = {}
        self._datasources = {}
        self.command_config = {"blocks": {}, "datasources": {}}

        # Retrieve configurations as defined in the json file
        config_file_path = os.path.join(os.getcwd(), "tools", "notion_config.json")
        
        # 
        if not os.path.exists(config_file_path):
            raise NotionException(f"Invalid config file path: {os.path.relpath(config_file_path, os.getcwd())}")

        with open(config_file_path) as f:
            try:
                config : dict = json.load(f)
            except:
                raise NotionException(f"Failed to parse config file: {os.path.relpath(config_file_path, os.getcwd())}.")

            # set up api key
            if "NOTION_KEY" not in config.keys():
                raise NotionException("Notion API key not found")

            self._api_key = config["NOTION_KEY"]

            # set up block and datasource configurations
            for k, v in config.items():
                if k == "NOTION_KEY":
                    continue
                
                if "type" not in v:
                    raise NotionException(f"Invalid endpoint configuration: [{k}]")
                else:
                    # checks: type = block or datasource
                    match v["type"]:
                        case "block":
                            self._blocks[k] = v
                            self.command_config["blocks"][k] = v["commands"]
                        case "datasource":
                            self._datasources[k] = v
                            self.command_config["datasources"][k] = v["commands"]
                        case _:
                            raise NotionException(f"Invalid type of endpoint: [{k}]")

    @classmethod
    async def create(cls) -> 'Notion':
        '''Asynchronous instantiation of a Notion object'''
        notion_obj = cls()

        # set up datasource objects for each datasource
        for datasource_name, config in notion_obj._datasources.items():
            notion_obj._datasources[datasource_name] = await Datasource.create(datasource_name, config, notion_obj._api_key)
        
        return notion_obj
    
    async def terminate(self):
        for _, datasource in self._datasources.items():
            await datasource.terminate()

    def help(self, command_type : str) -> str:
        '''
        Generate a formatted help string for the available Notion commands. This method
        supports two types of help string: info or syntax. Syntax help also supports entering
        a specific endpoint.

        TODO: assumes command = 'help notion ____ ____' max two inputs
        '''
        match command_type.split(" ")[0]:
            case "info":
                # Return information for commands
                help_string = "Notion command endpoints:\n"

                # Info about datasource endpoints
                if self._datasources:
                    help_string += "\nDatasources:\n"
                    for name, data in self._datasources.items():
                        help_string += f"\t{name}: {data.description}\n"

                # Info about block endpoints
                if self._blocks:
                    help_string += "\nBlocks:\n"
                    for name, data in self._blocks.items():
                        help_string += f"\t{name}: {data['description']}\n"
    
            case "syntax":
                # Check if user wanted the syntax for a specific endpoint
                endpoint = command_type.split(" ")[1] if len(command_type.split(" ")) == 2 else ""
                help_string = ""

                # Fuzzy match specified endpoint
                matched_endpoint = process.extractOne(endpoint, [*self.command_config["datasources"].keys(), *self.command_config["blocks"].keys()])
                if matched_endpoint[1] < 80: # type: ignore
                    help_string = f"{endpoint} is not a valid Notion endpoint.\n"
                else:
                    endpoint = matched_endpoint[0] # type: ignore

                # Return syntax for commands (only print when no specific endpoint is given)
                if not endpoint:
                    help_string += "Notion command syntax:\n"
                    help_string += "Each command and argument should be entered on a new line.\n"

                # Datasource endpoint syntax
                if self._datasources:

                    if not endpoint: # don't want to print this if user wanted specific endpoint
                        help_string += "\nDatasources:\n"

                    for name, data in self.command_config["datasources"].items():
                        # If a specific endpoint is requested, skip over every thing else
                        if endpoint and name != endpoint:
                            continue
                        
                        # Make indentation nicer 
                        indent = 0
                        if not endpoint:
                            indent = 3

                        help_string += " " * indent + name + "\n"

                        for command, args in data.items():
                            help_string += " " * (indent + 3) + command

                            # required arguments
                            for r_arg in args["required"]:
                                help_string += f" [{r_arg}]"
                            
                            # optional arguments
                            for flag, o_arg in args["optional"].items():
                                help_string += f" [{flag} {o_arg}]"
                            
                            help_string += "\n"

                        # If a specific endpoint is requested, add more details
                        if endpoint:
                            help_string += "\nProperties:\n" + self._datasources[name].property_help(indent + 3)

                # Block endpoint syntax
                if self._blocks:

                    if not endpoint: # don't want to print this if user wanted specific endpoint
                        help_string += "\nBlocks:\n"

                    for name, data in self.command_config["blocks"].items():
                        # If a specific endpoint is requested, skip over every thing else
                        if endpoint and name != endpoint:
                            continue

                        # Make indentation nicer 
                        indent = 0
                        if not endpoint:
                            indent = 3

                        help_string += " " * indent + name + "\n"

                        for command, args in data.items():
                            help_string += " " * (indent + 3) + command

                        # TODO: not sure what input style blocks config
            
            case _:
                help_string = f"The Notion help command can only be of type info or syntax, not {command_type}.\n"

        return "-" * 34 + "\n" + help_string + "-" * 34
    
    def parse_command(self, command : str) -> tuple:
        '''
        Checks for the command format, and returns a structured, dictionary 
        representation of the command. Note that this doesn't check for 
        input-notion compatibility, so incorrect value inputs will be checked
        down the line.
        '''
        command_parts = command.split("\n")
        
        # Check for valid endpoint
        endpoint = process.extractOne(command_parts[0], [*self._datasources.keys(), *self._blocks.keys()])
        if endpoint[1] < 85: # type: ignore
            return (0, f"[{command_parts[0]}] is an invalid Notion command endpoint.")
        endpoint_type = ""
        if endpoint in self._datasources:
            endpoint_type = "datasources"
        elif endpoint in self._blocks:
            endpoint_type = "blocks"
        
        # Check for valid action
        action = process.extractOne(command_parts[1], self.command_config[endpoint_type][endpoint].key())
        if action[1] < 85: # type: ignore
            return (0, f"[{command_parts[1]}] is an invalid action for [{endpoint}].")
        
        # Check for valid arguments
        req_argument_count, opt_argument_count = 0, 0
        required_args = self.command_config[endpoint_type][endpoint][action]["required"]
        optional_args = self.command_config[endpoint_type][endpoint][action]["optional"]
        command_arguments = {}
        for argument in command_parts[2:]:
            # Check type of input
            if argument[0] == "-":
                flag = argument.split(" ")[0]
                if flag not in optional_args:
                    return (0, f"[{flag}] is an invalid flag for [{endpoint}, {action}].")
                if flag in command_arguments:
                    return (0, f"Multiple [{flag}] flags for [{endpoint}, {action}].")
                command_arguments[optional_args[flag]] = "".join(argument.split(" ")[1:])
                opt_argument_count += 1
            else:
                try:
                    command_arguments[required_args[req_argument_count]] = argument
                    req_argument_count += 1
                except:
                    return (0, f"Provided too many arguments for [{endpoint}, {action}].")
        if req_argument_count != len(self.command_config[endpoint_type][endpoint][action]["required"]):
            return (0, f"Provided the wrong number of arguments for [{endpoint}, {action}].")
            
        return (1, {"type": endpoint_type, "endpoint": endpoint, "action": action, "arguments": command_arguments})
    
    async def run_command(self, command : str) -> str:
        status, payload = self.parse_command(command)

        # Command failed to be parsed
        if not status:
            return f"Error: {payload}"

        if payload["type"] == "datasources":
            endpoint = self._datasources[payload["endpoint"]]

            # Route to corresponding actions
            match payload["action"]:
                case "add":
                    return command + "\n" + await endpoint.add_page(payload["arguments"])

        return ""

    def __bool__(self) -> bool:
        '''Returns true if Notion object is set up according to the config file'''
        return bool(self._api_key) and (bool(self._blocks) or bool(self._datasources))

async def main():
    sys.excepthook = exception_handler
    
    obj = await Notion.create()
    if not obj:
        return
    
    # print(obj.help("syntax teseoirhwt"))

    # await obj.run_command("To-Dos\nadd\nTESTING\n-t afx")
    # await obj.run_command("testing\nadd\nTESTING\n-t afx")
    # await obj.run_command("To-Dos\nadd\nTESTING\nwoahhowiehri\n-t afx")
    # await obj.run_command("To-Dos\nadd\nTESTING\ntesingionwer")
    await obj.terminate()

if __name__ == "__main__":
    asyncio.run(main())