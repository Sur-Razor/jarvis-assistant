
import os
import json
import urllib.request
import urllib.parse

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
    print("JARVIS checking Telegram...")

    updates = telegram("getUpdates", {"timeout": 0})
    results = updates.get("result", [])

    last_update_id = None

    for item in results:
        last_update_id = item["update_id"]
        message = item.get("message", {})
        chat = message.get("chat", {})
        text = message.get("text", "").strip().lower()

        if str(chat.get("id")) != CHAT_ID:
            continue

        if text in ["/start", "hello", "hi"]:
            send_message("JARVIS systems online. Hello.")
        elif text == "/status":
            send_message("JARVIS Telegram connection: ONLINE.")
        elif text == "/help":
            send_message(
                "JARVIS commands:\n"
                "/start - Start JARVIS\n"
                "/status - Check connection\n"
                "/help - Show commands"
            )
        else:
            send_message(
                "Message received. My AI brain is not connected yet."
            )

    if last_update_id is not None:
        telegram("getUpdates", {
            "offset": last_update_id + 1,
            "timeout": 0
        })

    print("JARVIS check complete.")

if __name__ == "__main__":
    main()
