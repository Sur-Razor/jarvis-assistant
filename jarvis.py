
import os
import json
import csv
import io
import zipfile
import urllib.request
import urllib.parse
import urllib.error

from flask import Flask, request, jsonify, abort

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

API = f"https://api.telegram.org/bot{BOT_TOKEN}/"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

app = Flask(__name__)

# Temporary conversation and analytics memory.
conversation_history = {}
analytics_contexts = {}
processed_updates = set()


def telegram(method, data=None):
    payload = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(API + method, data=payload)

    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram request failed"))

    return result


def send_message(message, chat_id=None):
    chat_id = chat_id or CHAT_ID
    message = str(message)

    while message:
        chunk = message[:4000]

        if len(message) > 4000 and "\n" in chunk:
            chunk = chunk.rsplit("\n", 1)[0]

        telegram("sendMessage", {
            "chat_id": chat_id,
            "text": chunk
        })

        message = message[len(chunk):].lstrip()


def number(value, decimals=0):
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "Unavailable"


def read_youtube_zip(file_bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        csv_names = {
            name.rsplit("/", 1)[-1].lower(): name
            for name in archive.namelist()
        }

        table_name = csv_names.get("table data.csv")

        if not table_name:
            raise ValueError("Couldn't find Table data.csv in the ZIP.")

        with archive.open(table_name) as raw:
            text = io.TextIOWrapper(
                raw, encoding="utf-8-sig", newline=""
            )
            rows = list(csv.DictReader(text))

    total = next(
        (
            row for row in rows
            if (row.get("Content") or "").strip().lower() == "total"
            or (row.get("Video title") or "").strip().lower() == "total"
        ),
        None
    )

    if not total:
        raise ValueError("Couldn't find the Total row in the report.")

    videos = [
        row for row in rows
        if row is not total and (row.get("Video title") or "").strip()
    ]

    def get_views(row):
        try:
            return float((row.get("Views") or "0").replace(",", "") or 0)
        except ValueError:
            return 0

    videos.sort(key=get_views, reverse=True)

    lines = [
        "JARVIS — YOUTUBE ANALYTICS",
        "Reporting period: based on your uploaded export",
        "",
        f"Views: {number(total.get('Views'))}",
        f"Subscribers gained: +{number(total.get('Subscribers'))}",
        f"Watch time: {number(total.get('Watch time (hours)'), 1)} hours",
        f"Estimated revenue: ${number(total.get('Estimated revenue (USD)'), 2)}",
        f"New viewers: {number(total.get('New viewers'))}",
        f"Returning viewers: {number(total.get('Returning viewers'))}",
        f"Thumbnail impressions: {number(total.get('Thumbnail impressions'))}",
        f"Thumbnail CTR: {number(total.get('Thumbnail click-through rate (%)'), 2)}%",
        "",
        "TOP VIDEOS BY VIEWS:"
    ]

    for index, row in enumerate(videos[:5], 1):
        title = (row.get("Video title") or "Untitled").strip()

        if len(title) > 85:
            title = title[:82] + "..."

        lines.append(
            f"{index}. {title}\n"
            f"   {number(row.get('Views'))} views | "
            f"+{number(row.get('Subscribers'))} subscribers"
        )

    lines += [
        "",
        "Note: Daily chart data is labeled New viewers, not daily views.",
        "These are reporting-period analytics, not current public totals."
    ]

    return "\n".join(lines)


def handle_document(message):
    document = message.get("document", {})
    filename = (document.get("file_name") or "").lower()

    if not filename.endswith(".zip"):
        send_message("Please send your YouTube Studio export as a ZIP file.")
        return None

    file_id = document.get("file_id")

    if not file_id:
        send_message("I couldn't access that attachment. Try sending it again.")
        return None

    send_message("Received your YouTube analytics ZIP. Reading it now...")

    file_info = telegram("getFile", {
        "file_id": file_id
    }).get("result", {})

    file_path = file_info.get("file_path")

    if not file_path:
        raise ValueError("Telegram did not provide a downloadable file path.")

    req = urllib.request.Request(FILE_API + file_path)

    with urllib.request.urlopen(req, timeout=45) as response:
        file_bytes = response.read()

    report = read_youtube_zip(file_bytes)
    send_message(report)

    return report


def ask_jarvis(question, chat_id):
    system_prompt = (
        "You are JARVIS, a personal AI assistant. "
        "Your personality is formal, composed, intelligent, and professional. "
        "Address the user as Sir. "
        "Be helpful, clear, and concise. "
        "Do not use unnecessary emojis or slang. "
        "Never pretend to have performed an action you did not perform. "
        "Never invent live information or personal analytics. "
        "If you do not know something, say so honestly. "
        "Do not show your internal reasoning. Give only the final answer."
    )

    messages = [{"role": "system", "content": system_prompt}]

    analytics = analytics_contexts.get(chat_id)

    if analytics:
        messages.append({
            "role": "system",
            "content": (
                "The user provided this YouTube analytics report. "
                "Use it as factual context. Do not confuse reporting-period "
                "totals with current public totals.\n\n" + analytics
            )
        })

    history = conversation_history.get(chat_id, [])
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": question})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_completion_tokens": 500
    }

    req = urllib.request.Request(
        GROQ_API,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.loads(response.read().decode())

        answer = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not answer:
            return "I wasn't able to generate a response. Please try again."

        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer}
        ])

        conversation_history[chat_id] = history[-12:]

        return answer[:3900]

    except urllib.error.HTTPError as error:
        details = error.read().decode(errors="replace")
        print("Groq API error:", error.code, details[:1500])

        if error.code == 429:
            return "My AI service has reached its current usage limit. Please try again shortly."

        return "I encountered a problem with my AI service. Please try again."

    except Exception as error:
        print("AI error:", str(error))
        return "I couldn't process that request. Please try again."


def process_update(update):
    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != CHAT_ID:
        return

    user_text = (message.get("text") or "").strip()

    if message.get("document"):
        report = handle_document(message)

        if report:
            analytics_contexts[chat_id] = report

        return

    if user_text.lower() in ["/start", "hello", "hi"]:
        send_message(
            "Good evening, Sir. JARVIS systems are online. "
            "How may I assist you?",
            chat_id
        )

    elif user_text.lower() == "/status":
        send_message(
            "JARVIS Telegram connection: ONLINE.\n"
            "AI engine: Groq connected.",
            chat_id
        )

    elif user_text.lower() == "/help":
        send_message(
            "JARVIS COMMANDS\n\n"
            "/start - Start JARVIS\n"
            "/status - Check connection\n"
            "/help - Show commands\n\n"
            "You can also send me ordinary messages "
            "to speak with my AI assistant.",
            chat_id
        )

    elif user_text:
        send_message("Certainly, Sir. One moment.", chat_id)
        answer = ask_jarvis(user_text, chat_id)
        send_message(answer, chat_id)


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "assistant": "JARVIS"
    })


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if WEBHOOK_SECRET:
        supplied_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        if supplied_secret != WEBHOOK_SECRET:
            abort(403)

    update = request.get_json(silent=True) or {}
    update_id = update.get("update_id")

    if update_id is not None:
        if update_id in processed_updates:
            return jsonify({"ok": True})

        processed_updates.add(update_id)

        if len(processed_updates) > 1000:
            processed_updates.clear()
            processed_updates.add(update_id)

    try:
        process_update(update)
    except Exception as error:
        print("Update processing error:", str(error))

        try:
            send_message(
                "I encountered an error processing that request. Please try again."
            )
        except Exception as send_error:
            print("Telegram reply error:", str(send_error))

    return jsonify({"ok": True})
