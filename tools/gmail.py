import re
import base64
import os.path
import logging
import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from logging.handlers import RotatingFileHandler
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# my files
from tools.logger import PrettyFormatter

# If modifying these scopes, delete the file gmail_token.json.
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
	def __init__(self, logger):
		log_path = os.path.join(os.getcwd(), "logs", "gmail_bot.log")

		# Configure logger
		self.logger = logger

		# Configure username (email) and valid inboxes
		self.email = self.get_email()
		self.logger.info("[Gmail] Registered user email: " + str(self.email))

	def get_service(self):
		"""
		Set up and return credentials 
		"""
		creds = None
		root_dir = os.path.join(os.getcwd(), "tools")
		token_path = os.path.join(root_dir, "gmail_token.json")
		credential_path = os.path.join(root_dir, "credentials.json")

		# Load gmail_token.json if it exists
		if os.path.exists(token_path):
			try:
				creds = Credentials.from_authorized_user_file(token_path, SCOPES)
			except Exception as e:
				creds = None
				self.logger.error(f"[Gmail] Failed to parse gmail_token.json: {e}")

		# If there are no (valid) credentials available
		if not creds or not creds.valid:
			if creds and creds.expired and creds.refresh_token:
				# If the credentials is valid but expired, try to refresh the credentials.
				try:
					creds.refresh(Request())
					self.logger.info("[Gmail] Refreshed expired token.")
				except Exception as e:
					creds = None
					self.logger.error(f"[Gmail] Failed to refresh gmail_token.json: {e}")
			else:
				# We have to recreate creds, trigger manual login flow
				flow = InstalledAppFlow.from_client_secrets_file(
					credential_path, SCOPES
				)
				creds = flow.run_local_server(port=0)
				self.logger.info("[Gmail] Login successful.")

			# Save and return our credentials
			if creds:
				with open(token_path, "w") as token:
					token.write(creds.to_json())
				self.logger.info("[Gmail] Saved new gmail_token.json")
				
		if creds:
			try:
				return build("gmail", "v1", credentials=creds) 
			except HttpError as error:
				self.logger.error(f"[Gmail] An error occurred setting up service: {error}")
		self.logger.error(f"[Gmail] Gmail service object is NOT set up")
		return None

	def get_email(self):
		service = self.get_service()
		if service:
			# Get profile info
			profile = service.users().getProfile(userId='me').execute()
			return profile['emailAddress']
		self.logger.error("[Gmail] No service object")
		return None

	# send email with specified content and subject
	def send_message(self, to: str, content : str, subject : str = "Yours truly, MEEP"):
		"""Create and send an email message
		Print the returned  message id
		Returns: Message object, including message id
		"""
		service = self.get_service()
		if service:
			message = EmailMessage()

			message.set_content(content)

			message["To"] = to
			message["From"] = self.email
			message["Subject"] = subject

			# encoded message
			encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

			create_message = {"raw": encoded_message}
			send_message = service.users().messages().send(userId="me", body=create_message).execute()
			self.logger.info(f"[Gmail] Sent email: {content}")
		else:
			self.logger.error("[Gmail] No service object")

	def parse_plaintext(self, payload):
		content = ""
		if 'parts' in payload:
			# multipart message
			for part in payload['parts']:
				mime_type = part.get('mimeType')
				# we only need the plaintext content
				if mime_type == 'text/plain':
					data = part.get('body', {}).get('data')
					decoded_bytes = base64.urlsafe_b64decode(data.encode('UTF-8'))
					body = decoded_bytes.decode('utf-8')
					
					status = 0
					# We are using google voice so the content is sandwiched between elements linked to voice.google.com
					for chunk in body.split("\n"):
						if re.search("<https:\/\/voice\.google\.com.*>", chunk) or re.search("To respond to this text message, reply to this email or visit Google Voice.", chunk): # type: ignore
							status += 1
							if status >= 2:
								break
						else:
							content += chunk.strip("\r") + "\n"
			if content:
				return content.strip("\n")
			else:
				self.logger.error("[Gmail] Missing content in message payload")
		else:
			self.logger.error("[Gmail] Missing parts in message payload")
		return ""

	def get_unread_emails(self, chunk_size) -> list:
		emails = []
		service = self.get_service()
		if service:
			results = service.users().messages().list(userId='me', labelIds=["UNREAD"], maxResults=chunk_size).execute()
			messages = results.get('messages', [])

			if messages:
				self.logger.info(f"[Gmail] Got {len(messages)} new message(s)")
				for msg in messages:
					# For each unread email, get the relevant fields
					gmail_msg_id = msg['id']
					msg_data = service.users().messages().get(userId='me', id=gmail_msg_id, format='full').execute()
					headers = msg_data['payload']['headers']
					subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
					sender = next((h['value'] for h in headers if h['name'] == 'From'), None)
					msg_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)
					time_sent = next((h['value'] for h in headers if h['name'] == 'Date'), None)
					if time_sent:
						time_sent = parsedate_to_datetime(time_sent).strftime("%Y-%m-%d %I:%M:%S %p")
					time_seen = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
					thread_id = msg_data['threadId']
					
					if not (sender and msg_id): # If there is no sending or no message id
						self.logger.error("[Gmail] Missing sender or Message-ID")
					elif self.email and re.search(self.email, sender): # If this is a reply from MEEP
						self.logger.warning("[Gmail] Sender is MEEP, skipping this email")
						# TODO: maybe add a thing relabeling this email to ignored
					else:
						# Get content of email
						content = self.parse_plaintext(msg_data['payload'])
						
						email_obj = {
							"content": content,
							"time_sent": time_sent,
							"time_seen": time_seen,
							"type": "unconfirmed",
							"sender": sender,
							"subject": subject,
							"msg_id": msg_id,
							"thread_id": thread_id,
							"gmail_msg_id": gmail_msg_id
						}
						
						emails.append(email_obj)
						
						try:
							service.users().messages().modify(
								userId="me",
								id=gmail_msg_id,
								body={
									"removeLabelIds": ["UNREAD"]
								}
							).execute()
						except:
							self.logger.error(f"[Gmail] Failed to relabel email {content}")
		else:
			self.logger.error("[Gmail] Missing service or the specified inbox does not exist")

		return emails

	# check if there are any unread emails
	def check_inbox(self) -> bool:
		service = self.get_service()
		# service obj exists
		if service:
			results = service.users().messages().list(userId='me', labelIds=["UNREAD"]).execute()
			messages = results.get('messages', [])
			if not messages:
				return False
			else:
				return True
		self.logger.error("[Gmail] Missing service")
		return False

if __name__ == "__main__":
	# Configure logger
	logger = logging.getLogger("Testing MEEP Bot")
	logger.setLevel(logging.INFO)
	log_path = os.path.join(os.getcwd(), "logs", "test.log")

	handler = RotatingFileHandler(
		log_path,     			# path to log file
		maxBytes=5_000_000,     # 5 MB max file size
	)

	# Configure formatter for writing to log files
	formatter = PrettyFormatter(datefmt='%Y-%m-%d %I:%M:%S %p')	# date log format
	handler.setFormatter(formatter)
	logger.addHandler(handler)

	obj = Gmail(logger)
	obj.get_unread_emails(5)