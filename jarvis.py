
import os
import json
import csv
import io
import zipfile
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{BOT_TOKEN}/"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"


def telegram(method, data=None):
    payload = urllib.parse.urlencode(data or {}).encode()
    request = urllib.request.Request(API + method, data=payload)
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError(result.get("description", f"Telegram {method} failed"))
    return result


def send_message(text):
    telegram("sendMessage", {"chat_id": CHAT_ID, "text": text[:4000]})


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
        return

    file_id = document.get("file_id")
    if not file_id:
        send_message("I couldn't access that attachment. Try sending it again.")
        return

    send_message("Received your YouTube analytics ZIP. Reading it now...")

    file_info = telegram("getFile", {"file_id": file_id}).get("result", {})
    file_path = file_info.get("file_path")

    if not file_path:
        raise ValueError("Telegram did not provide a downloadable file path.")

    request = urllib.request.Request(FILE_API + file_path)

    with urllib.request.urlopen(request, timeout=45) as response:
        file_bytes = response.read()

    report = read_youtube_zip(file_bytes)
    send_message(report)


def main():
    print("JARVIS checking Telegram...")

    updates = telegram("getUpdates", {"timeout": 0}).get("result", [])
    last_update_id = None

    for item in updates:
        last_update_id = item["update_id"]
        message = item.get("message", {})
        chat = message.get("chat", {})

        if str(chat.get("id")) != CHAT_ID:
            continue

        text = (message.get("text") or "").strip().lower()

        try:
            if message.get("document"):
                handle_document(message)

            elif text in ["/start", "hello", "hi"]:
                send_message("JARVIS systems online. Hello.")

            elif text == "/status":
                send_message("JARVIS Telegram connection: ONLINE.")

            elif text == "/help":
                send_message(
                    "JARVIS commands:\n"
                    "/start - Start JARVIS\n"
                    "/status - Check connection\n"
                    "/help - Show commands\n\n"
                    "Send a YouTube Studio analytics ZIP to get a report."
                )

            elif text:
                send_message(
                    "Message received. I can currently answer "
                    "/status and /help, or analyze a YouTube Studio ZIP."
                )

        except Exception as error:
            print(f"Update processing error: {error}")
            send_message(f"I couldn't process that message: {str(error)[:500]}")

    if last_update_id is not None:
        telegram("getUpdates", {
            "offset": last_update_id + 1,
            "timeout": 0
        })

    print("JARVIS check complete.")


if __name__ == "__main__":
    main()
