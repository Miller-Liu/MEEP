import asyncio
from imapclient import IMAPClient

HOST = 'imap.gmail.com'
USERNAME = 'your_email@gmail.com'
PASSWORD = 'your_password'

def idle_loop():
    with IMAPClient(HOST) as client:
        client.login(USERNAME, PASSWORD)
        client.select_folder('INBOX')

        while True:
            print("Waiting for new messages...")
            # Enter IDLE mode (blocking)
            client.idle()
            responses = client.idle_check(timeout=30)  # Wait max 30 sec
            client.idle_done()

            if responses:
                print("New email detected!")
                # Fetch and process emails here
                messages = client.search('UNSEEN')
                for msgid in messages:
                    raw_message = client.fetch(msgid, ['RFC822'])
                    print(f"Got message {msgid}")

async def main():
    # Run the blocking idle_loop in a separate thread so it doesn't block asyncio event loop
    await asyncio.to_thread(idle_loop)

if __name__ == '__main__':
    asyncio.run(main())


class Chatbot:
    def __init__(self):
        self.client = IMAPClient(HOST)
        self.client.login(USERNAME, PASSWORD)
        self.client.select_folder("INBOX")

    def idle_loop(self):
        # Enter IDLE mode (blocking)
        self.client.idle()
        print("Connection is now in IDLE mode, send yourself an email or quit with ^c")
        
        while True:
            try:
                # Wait for up to 30 seconds for an IDLE response
                responses = self.client.idle_check(timeout=30)
            except KeyboardInterrupt:
                print("Gracefully exiting program...")
                break

            # if responses:
            #     print("New email detected!")
            #     # Fetch and process emails here
            #     messages = self.client.search('UNSEEN')
            #     for msgid in messages:
            #         raw_message = self.client.fetch(msgid, ['RFC822'])
            #         print(f"Got message {msgid}")

