
import os
import json
import urllib.request
import urllib.parse
import time

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

def telegram(method, data=None):
    payload = urllib.parse.urlencode(data or {}).encode()
    request = urllib.request.Request(API + method, data=payload)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())

def send_message(text):
    telegram("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text
    })

def main():
    print("JARVIS is starting...")
    send_message("JARVIS systems online. Telegram connection established.")

    updates = telegram("getUpdates", {"timeout": 0})
    offset = max(
        [item["update_id"] for item in updates.get("result", [])],
        default=0
    ) + 1

    while True:
        updates = telegram("getUpdates", {
            "timeout": 20,
            "offset": offset
        })

        for item in updates.get("result", []):
            offset = item["update_id"] + 1
            message = item.get("message", {})
            chat = message.get("chat", {})
            text = message.get("text", "")

            if str(chat.get("id")) != CHAT_ID:
                continue

            if text.lower() in ["/start", "hello", "hi"]:
                send_message("Hello. JARVIS is online and ready.")
            elif text.lower() == "/status":
                send_message("Telegram connection: ONLINE")
            elif text.lower() == "/help":
                send_message(
                    "JARVIS commands:\n"
                    "/start - Start JARVIS\n"
                    "/status - Check connection\n"
                    "/help - Show commands"
                )
            else:
                send_message(
                    "I received your message. My AI brain is not connected yet."
                )

if __name__ == "__main__":
    main()
