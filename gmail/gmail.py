import os.path

import logging
from logging.handlers import RotatingFileHandler
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import re
from queue import PriorityQueue

from tools.logger import PrettyFormatter

# If modifying these scopes, delete the file token.json.
SCOPES = [
	"https://www.googleapis.com/auth/gmail.readonly",
	"https://www.googleapis.com/auth/gmail.modify",
	"https://www.googleapis.com/auth/gmail.send"
]

'''
Gmail:
- logger: log info and errors log files
- email: the email that's logged in
- service: gmail service object
- inboxes: the inboxes of the email (only the ones we care about)
- email_queue: the emails that we have yet to process
'''
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
		self.logger.info("---------- Initialized logger object, script is running :) ----------")

		# Configure credentials
		self.service = self.get_service()
		self.logger.info("[✓] Gmail credentials configured successfully")

		# Configure username (email) and valid inboxes
		self.email = self.get_email()
		self.logger.info("[✓] Registered user email: " + str(self.email))
		self.inboxes = self.get_inboxes()
		self.logger.info("[✓] Registered email inboxes: " + str(self.inboxes))

		# Configure the email queue
		self.email_queue = PriorityQueue()

	def get_service(self):
		"""
		Set up and return credentials 
		"""
		creds = None
		root_dir = os.path.join(os.getcwd(), "gmail")
		token_path = os.path.join(root_dir, "token.json")
		credential_path = os.path.join(root_dir, "credentials.json")

		# Load token.json if it exists
		if os.path.exists(token_path):
			try:
				creds = Credentials.from_authorized_user_file(token_path, SCOPES)
				self.logger.info("[✓] Loaded token.json")
			except Exception as e:
				creds = None
				self.logger.error(f"[!] Failed to parse token.json: {e}")

		# If there are no (valid) credentials available
		if not creds or not creds.valid:
			if creds and creds.expired and creds.refresh_token:
				# If the credentials is valid but expired, try to refresh the credentials.
				try:
					creds.refresh(Request())
					self.logger.info("[↻] Refreshed expired token.")
				except Exception as e:
					creds = None
					self.logger.error(f"[!] Failed to refresh token: {e}")
			else:
				# We have to recreate creds, trigger manual login flow
				flow = InstalledAppFlow.from_client_secrets_file(
					credential_path, SCOPES
				)
				creds = flow.run_local_server(port=0)
				self.logger.info("[✓] Login successful.")

			# Save and return our credentials
			if creds:
				with open(token_path, "w") as token:
					token.write(creds.to_json())
				self.logger.info("[✓] Saved new token.json")
		try:
			return build("gmail", "v1", credentials=creds)
		except HttpError as error:
			self.logger.error(f"[!] An error occurred setting up service: {error}")
		self.logger.error(f"[!] Gmail service object is NOT set up")
		return None

	def get_email(self):
		if self.service:
			# Get the profile info
			profile = self.service.users().getProfile(userId='me').execute()
			return profile['emailAddress']
		return None

	def get_inboxes(self):
		if self.service:
			results = self.service.users().labels().list(userId="me").execute()
			labels = results.get("labels", [])

			if not labels:
				self.logger.error("[!] No inbox labels found.")
				return {}
			
			# We only care about: UNREAD and MEEP Seen (maybe INBOX, SENT, and IMPORTANT)
			inboxes = {}
			required_inboxes = ["UNREAD", "MEEP Seen"]
			for label in labels:
				if label["name"] in required_inboxes:
					inboxes[label["name"]] = label['id']
			for label in required_inboxes:
				if label not in inboxes.keys():
					self.logger.error("[!] Missing some inboxes in: " + str(required_inboxes))
			return inboxes
		self.logger.error("[!] No service object")
		return None

	def send_message(self, to: str, content : str, subject : str = "Yours truly, MEEP"):
		"""Create and send an email message
		Print the returned  message id
		Returns: Message object, including message id
		"""
		if self.service:
			message = EmailMessage()

			message.set_content(content)

			message["To"] = to
			message["From"] = self.email
			message["Subject"] = subject

			# encoded message
			encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

			create_message = {"raw": encoded_message}
			# pylint: disable=E1101
			send_message = (
				self.service.users()
				.messages()
				.send(userId="me", body=create_message)
				.execute()
			)
			self.logger.info(f"[✓] Sent email with id: {send_message['id']}")
		self.logger.error("[!] No service object")
	
	# right now only reads the first
	def get_inbox_emails(self, inbox):
		# service obj exists and unread is in inboxes
		if self.service and self.inboxes and inbox in self.inboxes.keys() and inbox != "MEEP Seen":
			results = self.service.users().messages().list(userId='me', labelIds=[self.inboxes[inbox]]).execute()
			messages = results.get('messages', [])

			if not messages:
				self.logger.info("[✓] No unread messages")
			else:
				self.logger.info(f"[✓] Got {len(messages)} unread message(s)")
				for msg in messages:
					# For each unread email, get the relevant fields
					gmail_msg_id = msg['id']
					msg_data = self.service.users().messages().get(userId='me', id=gmail_msg_id, format='full').execute()
					headers = msg_data['payload']['headers']
					subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
					sender = next((h['value'] for h in headers if h['name'] == 'From'), None)
					msg_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)
					timestamp_ms = int(msg_data['internalDate'])
					thread_id = msg_data['threadId']
					
					if not (sender and msg_id):
						self.logger.error("[!] Missing sender or Message-ID")
					elif self.email and re.search(self.email, sender):
						self.logger.warning("[!] Sender is MEEP, skipping this email")
					else:
						# Get body of email
						payload = msg_data['payload']
						content = ""
						status = 0
						if 'parts' in payload:
							# multipart message
							for part in payload['parts']:
								mime_type = part.get('mimeType')
								# we only need the plaintext content
								if mime_type == 'text/plain':
									data = part.get('body', {}).get('data')
									decoded_bytes = base64.urlsafe_b64decode(data.encode('UTF-8'))
									body = decoded_bytes.decode('utf-8')
									
									# We are using google voice so the content is sandwiched between elements linked to voice.google.com
									for chunk in body.split("\n"):
										if re.search("<https:\/\/voice\.google\.com.*>", chunk):
											status += 1
											if status >= 2:
												break
										else:
											content += chunk.strip("\r") + "\n"
							if content:
								content = content.strip("\n")
								email_obj = {
									"headers": headers,
									"subject": subject,
									"sender": sender,
									"msg_id": msg_id,
									"thread_id": thread_id,
									"content": content,
									"gmail_msg_id": gmail_msg_id
								}
								self.email_queue.put((timestamp_ms, email_obj))
								self.logger.info(f"[✓] The email from \"{sender}\" about \"{subject}\" is added to the queue")
								self.service.users().messages().modify(
									userId='me',
									id=gmail_msg_id,
									body={
										"addLabelIds": [self.inboxes['MEEP Seen']],
										"removeLabelIds": [self.inboxes['UNREAD']]
									}
								).execute()
								self.logger.info(f"[✓] The email has been relabeled from UNSEEN to MEEP Seen")
							else:
								self.logger.error("[!] Missing content in message payload")
						else:
							self.logger.error("[!] Missing parts in message payload")
				self.logger.info(f"[✓] {self.email_queue.qsize()} emails in the queue")
		else:
			self.logger.error("[!] Missing service or the specified inbox does not exist")

if __name__ == "__main__":
	obj = Gmail()
	obj.get_inbox_emails("UNREAD")