import os
import json
import logging
import asyncio
from datetime import datetime

# my files
from tools.notion import Notion

# notion finances ""
class ChatBot:
    def __init__(self) -> None:
        # , logger: logging.Logger = None
        # self.logger = logger

        # configure self.command_reference: used to find syntax for commands
        root_dir = os.path.join(os.getcwd(), "tools")
        database_config = os.path.join(root_dir, "command_config.json")
        with open(database_config, "r") as f:
            self.command_reference = json.load(f)
    
    @classmethod
    async def create(cls):
        chatbot_obj = cls()
        await chatbot_obj.set_up_notion()
        return chatbot_obj

    async def set_up_notion(self):
        self.notion_client = await Notion.create()

    def translate_default(self, default: str):
        if default[0] == "!":
            if default == "!today":
                return datetime.today().strftime('%m/%d/%Y')
        return default
    
    def is_command(self, input) -> bool:
        command = input.strip().split(" ")
        command_type, command_area = command[:2]
        command_type = command_type.lower()
        command_area = command_area.lower()
        ref = self.command_reference

        # check command type
        if command_type not in ref.keys():
            return False
        ref = ref[command_type]
        
        # check command area + set up function
        if command_area not in ref.keys():
            return False
        return True
    
    # return code, message
    async def command(self, input: str):
        command = input.strip().split(" ")
        command_type, command_area = command[:2]
        command_type = command_type.lower()
        command_area = command_area.lower()
        input_args = input[input.find(command[2]):]
        ref = self.command_reference

        # check command type
        if command_type not in ref.keys():
            return 0, f"{command_type} is not a valid command"
        ref = ref[command_type]
        
        # check command area + set up function
        if command_area not in ref.keys():
            return 0, f"{command_area} is not a valid command in {command_type}"
        ref = ref[command_area]
        command_function = getattr(self.notion_client, ref[0])

        # parsing input arguments
        current = ""
        command_args = []
        quote_started = False
        for i in input_args:
            if quote_started:
                if i == "\"":
                    quote_started = False
                    command_args.append(current)
                    current = ""
                else:
                    current += i
            else:
                if i == "\"":
                    quote_started = True
                elif i == " ":
                    if current:
                        command_args.append(current)
                        current = ""
                else:
                    current += i
        if current:
            command_args.append(current)

        # checking command arguments
        args, defaults = ref[1], ref[2]
        if len(command_args) > len(args):
            return 0, f"{len(args)} arguments expected, {len(command_args)} given"
        arguments = {}
        for i in range(len(args)):
            # if the user gave an argument, set that
            if i < len(command_args):
                arguments[args[i]] = command_args[i]
            # if the user did not, but there is a default, set that
            elif i < len(defaults) and defaults[i] != None:
                arguments[args[i]] = self.translate_default(defaults[i])
            # first time that there is no default and no user argument
            else:
                break
        
        code, message = await command_function(command_area, arguments)
        return code, message

async def main():
    obj = await ChatBot.create()
    code, msg = await obj.command(r'notion movies "materialists" 9 "Such a good movie')
    print(msg)


if __name__ == "__main__":
    asyncio.run(main())

     