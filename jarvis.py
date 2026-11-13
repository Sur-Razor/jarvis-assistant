
import os
import json
import csv
import io
import zipfile
import urllib.request
import urllib.parse
import subprocess

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

API = f"https://api.telegram.org/bot{BOT_TOKEN}/"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"

MODEL = "models/Qwen_Qwen3-0.6B-Q4_K_M.gguf"
LLAMA = "llama.cpp/build/bin/llama-cli"


def telegram(method, data=None):
    payload = urllib.parse.urlencode(data or {}).encode()
    request = urllib.request.Request(API + method, data=payload)

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError(
            result.get("description", f"Telegram {method} failed")
        )

    return result


def send_message(message):
    # Split long messages to stay within Telegram's message limit.
    message = str(message)

    while message:
        chunk = message[:4000]

        # Prefer splitting at a newline.
        if len(message) > 4000 and "\n" in chunk:
            chunk = chunk.rsplit("\n", 1)[0]

        telegram("sendMessage", {
            "chat_id": CHAT_ID,
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
                raw,
                encoding="utf-8-sig",
                newline=""
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

    videos.sort(
        key=lambda row: float(
            (row.get("Views") or "0").replace(",", "") or 0
        ),
        reverse=True
    )

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

    request = urllib.request.Request(FILE_API + file_path)

    with urllib.request.urlopen(request, timeout=45) as response:
        file_bytes = response.read()

    report = read_youtube_zip(file_bytes)
    send_message(report)

    return report


def ask_jarvis(question, analytics_context=None):
    if not os.path.isfile(MODEL):
        return "My AI model is currently unavailable. Please try again later."

    if not os.path.isfile(LLAMA):
        return "My AI engine is currently unavailable. Please try again later."

    system_prompt = (
        "You are JARVIS, a personal AI assistant. "
        "Your personality is formal, composed, intelligent, and professional. "
        "Address the user as Sir. "
        "Be helpful, clear, and concise. "
        "Do not use unnecessary emojis or slang. "
        "Never pretend to have performed an action you did not perform. "
        "Never invent live information or personal analytics. "
        "If you do not know something, say so honestly."
    )

    prompt = f"{system_prompt}\n\n"

    if analytics_context:
        prompt += (
            "The user has provided this YouTube analytics report. "
            "Use it as factual context when answering. "
            "Do not confuse reporting-period totals with current channel totals.\n\n"
            f"{analytics_context}\n\n"
        )

    prompt += f"User: {question} /no_think\nJARVIS:"

    command = [
        LLAMA,
        "-m", MODEL,
        "-p", prompt,
        "-n", "160",
        "-c", "2048",
        "--temp", "0.7",
        "--no-display-prompt",
        "--simple-io",
        "--single-turn"
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=100
        )

        if result.returncode != 0:
            print("AI engine error:", result.stderr[-2000:])
            return (
                "I encountered a problem processing that request. "
                "Please try again."
            )

        answer = result.stdout.strip()

if "JARVIS:" in answer:
    answer = answer.rsplit("JARVIS:", 1)[-1].strip()

if "[ Prompt:" in answer:
    answer = answer.split("[ Prompt:", 1)[0].strip()

if "\n>" in answer:
    answer = answer.split("\n>", 1)[0].strip()

        if not answer:
            return "I wasn't able to generate a response. Please try again."

        # Remove any repeated assistant label if the model generates one.
        if answer.startswith("JARVIS:"):
            answer = answer[len("JARVIS:"):].strip()

        return answer[:3900]

    except subprocess.TimeoutExpired:
        return (
            "That request took longer than expected. "
            "Please try a shorter question."
        )


def main():
    print("JARVIS checking Telegram...")

    updates = telegram("getUpdates", {
        "timeout": 0
    }).get("result", [])

    last_update_id = None
    analytics_context = None

    for item in updates:
        last_update_id = item["update_id"]

        message = item.get("message", {})
        chat = message.get("chat", {})

        if str(chat.get("id")) != CHAT_ID:
            continue

        user_text = (message.get("text") or "").strip()

        try:
            if message.get("document"):
                analytics_context = handle_document(message)

            elif user_text.lower() in ["/start", "hello", "hi"]:
                send_message(
                    "Good evening, Sir. JARVIS systems are online. "
                    "How may I assist you?"
                )

            elif user_text.lower() == "/status":
                send_message(
                    "JARVIS Telegram connection: ONLINE.\n"
                    "AI engine: available."
                )

            elif user_text.lower() == "/help":
                send_message(
                    "JARVIS COMMANDS\n\n"
                    "/start - Start JARVIS\n"
                    "/status - Check connection\n"
                    "/help - Show commands\n\n"
                    "You can also send me ordinary messages "
                    "to speak with my AI assistant."
                )

            elif user_text:
                send_message("Certainly, Sir. One moment.")

                answer = ask_jarvis(
                    user_text,
                    analytics_context
                )

                send_message(answer)

        except Exception as error:
            print(f"Update processing error: {error}")

            send_message(
                "I encountered an error processing that request: "
                f"{str(error)[:400]}"
            )

    if last_update_id is not None:
        telegram("getUpdates", {
            "offset": last_update_id + 1,
            "timeout": 0
        })

    print("JARVIS check complete.")


if __name__ == "__main__":
    main()
