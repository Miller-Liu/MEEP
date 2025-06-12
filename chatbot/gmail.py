import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import logging
from logging.handlers import RotatingFileHandler

from tools.logger import PrettyFormatter

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

class Gmail:
	def __init__(self):
		root_dir = os.path.join(os.getcwd(), "logs")
		log_path = os.path.join(root_dir, "gmail_bot.log")

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
		formatter = PrettyFormatter(
			f"[{'%(asctime)s':^22}] [{'%(levelname)s':^12s}] [{'%(filename)s:%(lineno)d':^}]: %(message)s", # log format
			datefmt='%Y-%m-%d %I:%M:%S %p'	# date log format
		)
		handler.setFormatter(formatter)
		self.logger.addHandler(handler)

		# Configure credentials
		self.get_credentials()


	def get_credentials(self):
		"""
		Set up token.json 
		"""
		creds = None
		root_dir = os.path.join(os.getcwd(), "chatbot")
		token_path = os.path.join(root_dir, "token.json")
		credential_path = os.path.join(root_dir, "credentials.json")

		# STEP 1: Load token.json if it exists
		if os.path.exists(token_path):
			try:
				creds = Credentials.from_authorized_user_file('token.json', SCOPES)
				self.logger.info("[✓] Loaded token.json")
			except Exception as e:
				creds = None
				self.logger.error(f"[!] Failed to parse token.json: {e}")

		# STEP 2: If there are no (valid) credentials available, let the user log in.
		if not creds or not creds.valid:
			if creds and creds.expired and creds.refresh_token:
				try:
					creds.refresh(Request())
					self.logger.info("[↻] Refreshed expired token.")
				except Exception as e:
					creds = None
					self.logger.error(f"[!] Failed to refresh token: {e}")
			else:
				# STEP 3: Trigger manual login flow
				flow = InstalledAppFlow.from_client_secrets_file(
					credential_path, SCOPES
				)
				creds = flow.run_local_server(port=0)
				self.logger.info("[✓] Login successful.")

			# STEP 4: Save credentials
			if creds:
				with open(token_path, "w") as token:
					token.write(creds.to_json())
				self.logger.info("[✓] Saved new token.json")

if __name__ == "__main__":
	obj = Gmail()