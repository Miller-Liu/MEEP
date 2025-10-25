import os
import time
import random
import asyncio
import logging
import aiosqlite
from fuzzywuzzy import process
from typing import Literal, Optional
from tools.notion import Notion

class ProcessorException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
    
    def __str__(self) -> str:
        return f"[!] Processor Exception: {self.args[0]}"

def exception_handler(exception_type, exception, traceback):
    # All your trace are belong to us!
    print(exception)

class Processor:
    def __init__(self, logger : logging.Logger) -> None:
        self.chat_started : bool = False
        self._notion : Notion
        self.logger : logging.Logger = logger
    
    @classmethod
    async def create(cls, logger : logging.Logger) -> 'Processor':
        processor_obj = cls(logger)
        
        ok = await processor_obj.init_db()
        if not ok:
            raise ProcessorException(f"Initializing DB setup failed.")
        
        processor_obj._notion = await Notion.create()

        return processor_obj

    async def init_db(self, retries=5, delay=0.5) -> bool:
        """Initialize async DB connection and enable WAL mode with retry."""
        for _ in range(retries):
            try:
                self._inbox = await aiosqlite.connect(os.path.join(os.getcwd(), "memory", "inbox.db"), timeout=10)
                await self._inbox.execute("PRAGMA journal_mode=WAL;")
                await self._inbox.execute("PRAGMA synchronous=NORMAL;")
                await self._inbox.execute("""
                    CREATE TABLE IF NOT EXISTS emails (
                        content TEXT,
                        time_sent TEXT,
                        time_seen TEXT,
                        type TEXT,
                        sender TEXT,
                        subject TEXT,
                        msg_id TEXT PRIMARY KEY,
                        thread_id TEXT,
                        gmail_msg_id TEXT
                    )
                """)
                await self._inbox.commit()
                self._inbox.row_factory = aiosqlite.Row
        
                self._outbox = await aiosqlite.connect(os.path.join(os.getcwd(), "memory", "outbox.db"), timeout=10)
                await self._outbox.execute("PRAGMA journal_mode=WAL;")
                await self._outbox.execute("PRAGMA synchronous=NORMAL;")
                await self._outbox.execute("""
                    CREATE TABLE IF NOT EXISTS emails (
                        content TEXT,
                        time_sent TEXT,
                        sender TEXT,
                        subject TEXT,
                        msg_id TEXT PRIMARY KEY,
                        thread_id TEXT,
                        gmail_msg_id TEXT
                    )
                """)
                await self._outbox.commit()
                self._outbox.row_factory = aiosqlite.Row

                return True
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower():
                    await asyncio.sleep(delay)
            except Exception as e:
                raise ProcessorException(e)
        return False
    
    async def terminate(self, retries=5, delay=0.5):
        for _ in range(retries):
            try:
                await self._inbox.execute("PRAGMA wal_checkpoint(TRUNCATE);") 
                await self._inbox.commit()

                await self._outbox.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                await self._outbox.commit()
                break
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower():
                    await asyncio.sleep(delay + random.random() * 0.2)
            except Exception as e:
                pass
            
        await self._inbox.close()
        await self._outbox.close()

        # Remove WAL and SHM files
        for db_name in ["inbox", "outbox"]:
            db_path = os.path.join(os.getcwd(), "memory", f"{db_name}.db")
            for ext in ["-wal", "-shm"]:
                try:
                    os.remove(db_path + ext)
                except FileNotFoundError:
                    pass

        await self._notion.terminate()

    # ----------------------------
    # Database Operations wrapper
    # ----------------------------

    async def execute(self, db_name : Literal["inbox", "outbox"], query: str, params: tuple = (), retries=5, delay=0.5) -> Optional[aiosqlite.Cursor]:
        for _ in range(retries):
            try:
                db = self._inbox if db_name == "inbox" else self._outbox
                return await db.execute(query, params)
            except aiosqlite.OperationalError as e:
                if "locked" in str(e).lower():
                    await asyncio.sleep(delay)
            except Exception:
                self.logger.exception(f"[Processor] ")
                pass
        return None
    
    # ----------------------------
    # Application Logic
    # ----------------------------

    async def get_outgoing_emails(self, chunk_size):
        cursor = await self.execute("outbox", "SELECT * FROM emails LIMIT ?", (chunk_size,))
        if not cursor:
            return []
        return await cursor.fetchall()

    async def remove_from_outbox(self, emails):
        for email_obj in emails:
            await self.execute(
                "outbox", 
                "DELETE FROM emails WHERE msg_id = ?", 
                (email_obj["msg_id"],)
            )
            self.logger.info(f"[Processor] Deleted \"{email_obj['content']}\" from outbox")
        await self._outbox.commit()

    async def add_emails_to_inbox(self, emails):
        for email_obj in emails:
            await self.execute(
                "inbox", 
                """
                INSERT OR REPLACE INTO emails
                (content, time_sent, time_seen, type, sender, subject, msg_id, thread_id, gmail_msg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, 
                (
                    email_obj["content"],
                    email_obj["time_sent"],
                    email_obj["time_seen"],
                    "unconfirmed",
                    email_obj["sender"],
                    email_obj["subject"],
                    email_obj["msg_id"],
                    email_obj["thread_id"],
                    email_obj["gmail_msg_id"]
                )
            )
        await self._inbox.commit()
    
    async def reply_emails(self, emails):
        for message, email_obj in emails:
            await self.execute(
                "outbox", 
                """
                INSERT OR REPLACE INTO emails
                (content, time_sent, sender, subject, msg_id, thread_id, gmail_msg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, 
                (
                    message,
                    email_obj["time_sent"],
                    email_obj["sender"],
                    email_obj["subject"],
                    email_obj["msg_id"],
                    email_obj["thread_id"],
                    email_obj["gmail_msg_id"]
                )
            )
            await self.execute(
                "inbox", 
                "DELETE FROM emails WHERE msg_id = ?", 
                (email_obj["msg_id"],)
            )
        await self._inbox.commit()
        await self._outbox.commit()

    async def classify_emails(self, chunk_size) -> None:
        cursor = await self.execute("inbox", "SELECT * FROM emails WHERE type = 'unconfirmed' LIMIT ?", (chunk_size,))
        if not cursor:
            return

        emails = await cursor.fetchall()

        for email in emails:
            message = email["content"]
            
            if len(message) <= 1:
                await self.execute("inbox", "DELETE FROM emails WHERE msg_id = ?", (email["msg_id"],))
                continue
            first_line = message.split("\n")[0]
            
            # Chatbot mode
            chat_commands = ['hey meep', 'bye meep']
            matched_command = process.extractOne(first_line, chat_commands)
            if matched_command and matched_command[1] >= 80:
                if not self.chat_started and matched_command[0] == 'hey meep':
                    self.chat_started = True
                    await self.execute("inbox", "UPDATE emails SET type = ? WHERE msg_id = ?", ("Chat", email["msg_id"]))
                    self.logger.info(f"[Processor] Chat mode started")
                    continue
                if self.chat_started and matched_command[0] == 'bye meep':
                    self.chat_started = False
                    await self.execute("inbox", "UPDATE emails SET type = ? WHERE msg_id = ?", ("Chat", email["msg_id"]))
                    self.logger.info(f"[Processor] Chat mode ended")
                    continue
            if self.chat_started:
                await self.execute("inbox", "UPDATE emails SET type = ? WHERE msg_id = ?", ("Chat", email["msg_id"]))
                self.logger.info(f"[Processor] Message \"{email['content']}\" labeled as chat")
                continue
            
            # Command
            if first_line[0] == "!":
                await self.execute("inbox", "UPDATE emails SET type = ? WHERE msg_id = ?", ("Command", email["msg_id"]))
                self.logger.info(f"[Processor] Message \"{email['content']}\" labeled as command")
                continue
            
            await self.execute("inbox", "DELETE FROM emails WHERE msg_id = ?", (email["msg_id"],))
            self.logger.info(f"[Processor] Message \"{email['content']}\" ignored")
            continue
        
        await self._inbox.commit()

    async def run_commands(self, chunk_size) -> None:
        cursor = await self.execute("inbox", "SELECT * FROM emails WHERE type = 'Command' LIMIT ?", (chunk_size,))
        if not cursor:
            return

        emails = await cursor.fetchall()
        reply_drafts = []
        for email in emails:
            message = email["content"].split("\n")
            command = message[0][1:]
            command_types = ["notion"]
            return_message = ""

            # Match kind of command
            matched_command = process.extractOne(command, command_types)
            if not matched_command or matched_command[1] < 80:
                return_message = f"Invalid command {command}"
            else:
                # Route to correct command executer
                match matched_command[0]:
                    case "notion":
                        return_message = await self._notion.run_command("".join(message[1:]))
            
            if return_message:
                reply_drafts.append((return_message, email))
        
        await self.reply_emails(reply_drafts)

    async def process_loop(self, stop_event : asyncio.Event, chunk_size):
        state = "INACTIVE"
        last_activity = time.time()
        self.logger.info("[Processor Loop] Initialized processor loop")

        try:
            while not stop_event.is_set():
                # Check for work
                cursor = await self.execute(
                    "inbox", 
                    "SELECT COUNT(*) as cnt FROM emails WHERE type IN ('unconfirmed', 'Command')"
                )
                if not cursor:
                    continue
                count = (await cursor.fetchone())["cnt"] # type: ignore

                # INACTIVE MODE
                if count == 0:
                    # No new work for over one minute -> INACTIVE
                    if state != "INACTIVE" and time.time() - last_activity > 1 * 60:
                        self.logger.info("[Processor Loop] Switching to INACTIVE mode.")
                        state = "INACTIVE"
                    await asyncio.sleep(5)
                    continue

                # There is work → ACTIVE
                if count > 0 and state != "ACTIVE":
                    self.logger.info("[Processor Loop] Switching to ACTIVE mode.")
                    state = "ACTIVE"

                await self.classify_emails(chunk_size)
                await self.run_commands(chunk_size)
                last_activity = time.time()

                # Small delay to prevent tight loop
                await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.exception(f"[Processor Loop] Unexpected error: {e}")
