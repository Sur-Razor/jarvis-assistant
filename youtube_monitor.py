
import os
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

STATE_FILE = "youtube_monitor_state.json"
STATE_BRANCH = "jarvis-state"
TIMEZONE = ZoneInfo("America/Los_Angeles")

MAJOR_MILESTONES = {
    15000, 20000, 25000, 30000, 40000,
    50000, 75000, 100000, 125000, 150000,
    175000, 200000
}


def api_request(url, method="GET", data=None, headers=None):
    request_headers = {
        "User-Agent": "JARVIS/1.0"
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode())


def youtube_request(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    query = urllib.parse.urlencode(params)

    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{query}"

    return api_request(url)


def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode()

    result = api_request(url, method="POST", data=data)

    if not result.get("ok"):
        raise RuntimeError("Telegram message could not be sent.")


def github_state_url():
    repo = urllib.parse.quote(GITHUB_REPOSITORY, safe="/")
    path = urllib.parse.quote(STATE_FILE, safe="/")

    return (
        f"https://api.github.com/repos/{repo}/contents/{path}"
        f"?ref={STATE_BRANCH}"
    )


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def load_state():
    try:
        result = api_request(
            github_state_url(),
            headers=github_headers()
        )

        content = base64.b64decode(
            result["content"]
        ).decode()

        state = json.loads(content)
        state["_sha"] = result["sha"]

        return state

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def save_state(state):
    sha = state.pop("_sha", None)

    content = json.dumps(
        state,
        indent=4
    )

    encoded_content = base64.b64encode(
        content.encode()
    ).decode()

    payload = {
    "message": "Update JARVIS YouTube monitoring history",
    "content": encoded_content,
    "branch": STATE_BRANCH
}

    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode()

    result = api_request(
        github_state_url(),
        method="PUT",
        data=data,
        headers=github_headers()
    )

    state["_sha"] = result["content"]["sha"]


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
            video_id = video.get(
                "resourceId", {}
            ).get("videoId")

            if video_id:
                latest_video = {
                    "id": video_id,
                    "title": video.get("title", "New upload")
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

    # First run establishes the starting baseline.
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

    # Subscriber milestone alerts.
    if subscribers > previous_subscribers:
        first_goal = (previous_subscribers // 100 + 1) * 100
        last_goal = (subscribers // 100) * 100

        reached_goals = []

        for goal in range(first_goal, last_goal + 1, 100):
            if goal in MAJOR_MILESTONES:
                reached_goals.append(
                    f"MAJOR MILESTONE: {goal:,} subscribers!"
                )
            else:
                reached_goals.append(
                    f"Subscriber goal reached: approximately {goal:,}"
                )

        if reached_goals:
            send_telegram(
                "JARVIS — SUBSCRIBER MILESTONES\n\n"
                + "\n".join(reached_goals)
            )

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
        starting_subscribers = state.get(
            "daily_start_subscribers", previous_subscribers
        )

        starting_views = state.get(
            "daily_start_views", state["last_views"]
        )

        subscriber_change = subscribers - starting_subscribers
        view_change = views - starting_views

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
