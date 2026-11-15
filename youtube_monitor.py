
import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = "youtube_monitor_state.json"
TIMEZONE = ZoneInfo("America/Los_Angeles")

MAJOR_MILESTONES = {
    15000, 20000, 25000, 30000, 40000,
    50000, 75000, 100000, 125000, 150000,
    175000, 200000
}


def youtube_request(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    query = urllib.parse.urlencode(params)
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{query}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JARVIS/1.0"}
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=25) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError("Telegram message could not be sent.")


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    with open(STATE_FILE, "r") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=4)


def get_channel_data():
    data = youtube_request("channels", {
        "part": "snippet,statistics,contentDetails",
        "id": YOUTUBE_CHANNEL_ID
    })

    items = data.get("items", [])

    if not items:
        raise RuntimeError("YouTube channel could not be found.")

    channel = items[0]
    stats = channel.get("statistics", {})

    subscribers = int(stats.get("subscriberCount", 0))
    views = int(stats.get("viewCount", 0))

    uploads_playlist = (
        channel.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    latest_video = None

    if uploads_playlist:
        playlist = youtube_request("playlistItems", {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": 1
        })

        videos = playlist.get("items", [])

        if videos:
            video = videos[0]["snippet"]
            resource = video.get("resourceId", {})

            video_id = resource.get("videoId")

            if video_id:
                latest_video = {
                    "id": video_id,
                    "title": video.get("title", "New upload"),
                    "date": video.get("publishedAt", "")
                }

    return {
        "subscribers": subscribers,
        "views": views,
        "latest_video": latest_video
    }


def monitor():
    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")

    data = get_channel_data()

    subscribers = data["subscribers"]
    views = data["views"]
    latest_video = data["latest_video"]

    state = load_state()

    # First run: establish a baseline without sending old alerts.
    if state is None:
        state = {
            "last_subscribers": subscribers,
            "last_views": views,
            "last_video_id": (
                latest_video["id"] if latest_video else None
            ),
            "last_daily_date": "",
            "daily_start_subscribers": subscribers,
            "daily_start_views": views
        }

        save_state(state)

        send_telegram(
            "JARVIS YOUTUBE MONITOR\n\n"
            "Monitoring is now active.\n"
            f"Current subscribers: {subscribers:,}\n"
            f"Total views: {views:,}\n\n"
            "I will check your channel every 15 minutes."
        )

        print("Monitoring initialized.")
        return

    previous_subscribers = state["last_subscribers"]
    previous_views = state["last_views"]

    # Subscriber milestone alerts.
    if subscribers > previous_subscribers:
        first_goal = (previous_subscribers // 100 + 1) * 100
        last_goal = (subscribers // 100) * 100

        for goal in range(first_goal, last_goal + 1, 100):
            if goal in MAJOR_MILESTONES:
                message = (
                    "JARVIS — MAJOR SUBSCRIBER MILESTONE!\n\n"
                    f"Congratulations! Sur-Razor has reached "
                    f"{goal:,} subscribers!"
                )
            else:
                message = (
                    "JARVIS — SUBSCRIBER GOAL REACHED!\n\n"
                    f"Sur-Razor has reached approximately "
                    f"{goal:,} subscribers."
                )

            send_telegram(message)

    # New upload alert.
    if latest_video:
        previous_video_id = state.get("last_video_id")

        if previous_video_id and latest_video["id"] != previous_video_id:
            send_telegram(
                "JARVIS — NEW YOUTUBE UPLOAD!\n\n"
                f"{latest_video['title']}\n\n"
                f"https://www.youtube.com/watch?v={latest_video['id']}"
            )

        state["last_video_id"] = latest_video["id"]

    # Daily summary at approximately 6 PM Pacific.
    if now.hour == 18 and state.get("last_daily_date") != today:
        daily_start_subscribers = state.get(
            "daily_start_subscribers", previous_subscribers
        )

        daily_start_views = state.get(
            "daily_start_views", previous_views
        )

        subscriber_change = subscribers - daily_start_subscribers
        view_change = views - daily_start_views

        send_telegram(
            "JARVIS — DAILY YOUTUBE SUMMARY\n\n"
            f"Date: {today}\n\n"
            f"Subscribers: {subscribers:,}\n"
            f"Subscriber change: {subscriber_change:+,}\n\n"
            f"Total channel views: {views:,}\n"
            f"View change: {view_change:+,}\n\n"
            "Monitoring remains active."
        )

        state["last_daily_date"] = today
        state["daily_start_subscribers"] = subscribers
        state["daily_start_views"] = views

    state["last_subscribers"] = subscribers
    state["last_views"] = views

    save_state(state)

    print(
        f"Monitor completed: {subscribers:,} subscribers, "
        f"{views:,} views."
    )


if __name__ == "__main__":
    try:
        monitor()
    except Exception as error:
        print("YouTube monitoring error:", str(error))
        raise
