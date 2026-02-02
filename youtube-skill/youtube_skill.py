#!/usr/bin/env python3
"""
YouTube Skill - Manage videos, playlists, and channels.

Usage:
    python youtube_skill.py me [--account EMAIL]
    python youtube_skill.py channels [--account EMAIL]
    python youtube_skill.py videos [--channel CHANNEL_ID] [--limit N] [--account EMAIL]
    python youtube_skill.py video VIDEO_ID [--account EMAIL]
    python youtube_skill.py search "query" [--limit N] [--type video|channel|playlist]
    python youtube_skill.py playlists [--channel CHANNEL_ID] [--account EMAIL]
    python youtube_skill.py playlist PLAYLIST_ID [--limit N] [--account EMAIL]
    python youtube_skill.py create-playlist --title "..." [--description "..."] [--privacy public|private|unlisted]
    python youtube_skill.py add-to-playlist PLAYLIST_ID --video VIDEO_ID [--account EMAIL]
    python youtube_skill.py remove-from-playlist PLAYLIST_ITEM_ID [--account EMAIL]
    python youtube_skill.py comments VIDEO_ID [--limit N]
    python youtube_skill.py comment VIDEO_ID --text "..." [--account EMAIL]
    python youtube_skill.py reply COMMENT_ID --text "..." [--account EMAIL]
    python youtube_skill.py subscriptions [--account EMAIL]
    python youtube_skill.py subscribe CHANNEL_ID [--account EMAIL]
    python youtube_skill.py unsubscribe SUBSCRIPTION_ID [--account EMAIL]
    python youtube_skill.py upload --file PATH --title "..." [--description "..."] [--privacy public|private|unlisted]
    python youtube_skill.py accounts
    python youtube_skill.py login [--account EMAIL]
    python youtube_skill.py logout [--account EMAIL]
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_file() -> Path:
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    for alt in ["gmail-skill", "google-sheets-skill"]:
        p = Path.home() / f".claude/skills/{alt}/credentials.json"
        if p.exists():
            return p
    print("No credentials.json found. Enable YouTube Data API v3 and set up OAuth.")
    sys.exit(1)


def get_token_path(account: str = None) -> Path:
    if account:
        safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in account)
        return TOKENS_DIR / f"token_{safe}.json"
    tokens = list(TOKENS_DIR.glob("token_*.json"))
    return tokens[0] if tokens else TOKENS_DIR / "token_default.json"


def get_credentials(account: str = None):
    creds_file = get_credentials_file()
    token_path = get_token_path(account)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=9993)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def get_service(account: str = None):
    return build("youtube", "v3", credentials=get_credentials(account))


# Commands

def cmd_accounts(args):
    accounts = [{"name": f.stem.replace("token_", "")} for f in TOKENS_DIR.glob("token_*.json")]
    print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    get_credentials(args.account)
    print(json.dumps({"success": True}, indent=2))


def cmd_logout(args):
    path = get_token_path(args.account)
    if path.exists():
        path.unlink()
    print(json.dumps({"success": True}, indent=2))


def cmd_me(args):
    service = get_service(args.account)
    result = service.channels().list(part="snippet,statistics", mine=True).execute()
    items = result.get("items", [])
    if items:
        ch = items[0]
        print(json.dumps({
            "id": ch["id"],
            "title": ch["snippet"]["title"],
            "description": ch["snippet"].get("description", "")[:200],
            "subscriberCount": ch["statistics"].get("subscriberCount"),
            "videoCount": ch["statistics"].get("videoCount"),
            "viewCount": ch["statistics"].get("viewCount"),
        }, indent=2))
    else:
        print(json.dumps({"error": "No channel found"}, indent=2))


def cmd_channels(args):
    service = get_service(args.account)
    result = service.channels().list(part="snippet,statistics", mine=True).execute()
    channels = [{
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "subscriberCount": ch["statistics"].get("subscriberCount"),
    } for ch in result.get("items", [])]
    print(json.dumps({"channels": channels}, indent=2))


def cmd_videos(args):
    service = get_service(args.account)

    if args.channel:
        result = service.search().list(
            part="snippet",
            channelId=args.channel,
            maxResults=args.limit,
            order="date",
            type="video"
        ).execute()
    else:
        # Get own channel's videos
        ch_result = service.channels().list(part="contentDetails", mine=True).execute()
        if not ch_result.get("items"):
            print(json.dumps({"error": "No channel found"}, indent=2))
            return
        uploads_id = ch_result["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        result = service.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=args.limit
        ).execute()

    videos = [{
        "videoId": v["snippet"].get("resourceId", {}).get("videoId") or v.get("id", {}).get("videoId"),
        "title": v["snippet"]["title"],
        "publishedAt": v["snippet"]["publishedAt"],
        "description": v["snippet"].get("description", "")[:100],
    } for v in result.get("items", [])]

    print(json.dumps({"videos": videos, "count": len(videos)}, indent=2))


def cmd_video(args):
    service = get_service(args.account)
    result = service.videos().list(
        part="snippet,statistics,contentDetails",
        id=args.video_id
    ).execute()

    items = result.get("items", [])
    if items:
        v = items[0]
        print(json.dumps({
            "id": v["id"],
            "title": v["snippet"]["title"],
            "description": v["snippet"].get("description", "")[:500],
            "publishedAt": v["snippet"]["publishedAt"],
            "channelTitle": v["snippet"]["channelTitle"],
            "viewCount": v["statistics"].get("viewCount"),
            "likeCount": v["statistics"].get("likeCount"),
            "commentCount": v["statistics"].get("commentCount"),
            "duration": v["contentDetails"]["duration"],
        }, indent=2))
    else:
        print(json.dumps({"error": "Video not found"}, indent=2))


def cmd_search(args):
    service = get_service(args.account)
    result = service.search().list(
        part="snippet",
        q=args.query,
        maxResults=args.limit,
        type=args.type
    ).execute()

    items = [{
        "id": i["id"].get("videoId") or i["id"].get("channelId") or i["id"].get("playlistId"),
        "kind": i["id"]["kind"],
        "title": i["snippet"]["title"],
        "description": i["snippet"].get("description", "")[:100],
        "channelTitle": i["snippet"]["channelTitle"],
    } for i in result.get("items", [])]

    print(json.dumps({"query": args.query, "results": items}, indent=2))


def cmd_playlists(args):
    service = get_service(args.account)

    if args.channel:
        result = service.playlists().list(
            part="snippet",
            channelId=args.channel,
            maxResults=50
        ).execute()
    else:
        result = service.playlists().list(part="snippet", mine=True, maxResults=50).execute()

    playlists = [{
        "id": p["id"],
        "title": p["snippet"]["title"],
        "description": p["snippet"].get("description", "")[:100],
    } for p in result.get("items", [])]

    print(json.dumps({"playlists": playlists}, indent=2))


def cmd_playlist(args):
    service = get_service(args.account)
    result = service.playlistItems().list(
        part="snippet",
        playlistId=args.playlist_id,
        maxResults=args.limit
    ).execute()

    items = [{
        "playlistItemId": i["id"],
        "videoId": i["snippet"]["resourceId"]["videoId"],
        "title": i["snippet"]["title"],
        "position": i["snippet"]["position"],
    } for i in result.get("items", [])]

    print(json.dumps({"playlistId": args.playlist_id, "items": items}, indent=2))


def cmd_create_playlist(args):
    service = get_service(args.account)
    result = service.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": args.title,
                "description": args.description or "",
            },
            "status": {"privacyStatus": args.privacy}
        }
    ).execute()

    print(json.dumps({
        "success": True,
        "playlistId": result["id"],
        "title": result["snippet"]["title"],
    }, indent=2))


def cmd_add_to_playlist(args):
    service = get_service(args.account)
    result = service.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": args.playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": args.video}
            }
        }
    ).execute()

    print(json.dumps({"success": True, "playlistItemId": result["id"]}, indent=2))


def cmd_remove_from_playlist(args):
    service = get_service(args.account)
    service.playlistItems().delete(id=args.playlist_item_id).execute()
    print(json.dumps({"success": True}, indent=2))


def cmd_comments(args):
    service = get_service(args.account)
    result = service.commentThreads().list(
        part="snippet",
        videoId=args.video_id,
        maxResults=args.limit
    ).execute()

    comments = [{
        "id": c["id"],
        "author": c["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
        "text": c["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300],
        "likeCount": c["snippet"]["topLevelComment"]["snippet"]["likeCount"],
        "publishedAt": c["snippet"]["topLevelComment"]["snippet"]["publishedAt"],
        "replyCount": c["snippet"]["totalReplyCount"],
    } for c in result.get("items", [])]

    print(json.dumps({"comments": comments}, indent=2))


def cmd_comment(args):
    service = get_service(args.account)
    result = service.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": args.video_id,
                "topLevelComment": {"snippet": {"textOriginal": args.text}}
            }
        }
    ).execute()

    print(json.dumps({"success": True, "commentId": result["id"]}, indent=2))


def cmd_reply(args):
    service = get_service(args.account)
    result = service.comments().insert(
        part="snippet",
        body={
            "snippet": {
                "parentId": args.comment_id,
                "textOriginal": args.text
            }
        }
    ).execute()

    print(json.dumps({"success": True, "replyId": result["id"]}, indent=2))


def cmd_subscriptions(args):
    service = get_service(args.account)
    result = service.subscriptions().list(part="snippet", mine=True, maxResults=50).execute()

    subs = [{
        "subscriptionId": s["id"],
        "channelId": s["snippet"]["resourceId"]["channelId"],
        "title": s["snippet"]["title"],
    } for s in result.get("items", [])]

    print(json.dumps({"subscriptions": subs}, indent=2))


def cmd_subscribe(args):
    service = get_service(args.account)
    result = service.subscriptions().insert(
        part="snippet",
        body={
            "snippet": {
                "resourceId": {"kind": "youtube#channel", "channelId": args.channel_id}
            }
        }
    ).execute()

    print(json.dumps({"success": True, "subscriptionId": result["id"]}, indent=2))


def cmd_unsubscribe(args):
    service = get_service(args.account)
    service.subscriptions().delete(id=args.subscription_id).execute()
    print(json.dumps({"success": True}, indent=2))


def cmd_upload(args):
    service = get_service(args.account)

    body = {
        "snippet": {
            "title": args.title,
            "description": args.description or "",
        },
        "status": {"privacyStatus": args.privacy}
    }

    media = MediaFileUpload(args.file, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading... {int(status.progress() * 100)}%", file=sys.stderr)

    print(json.dumps({
        "success": True,
        "videoId": response["id"],
        "title": response["snippet"]["title"],
    }, indent=2))


def add_account_arg(p):
    p.add_argument("--account", "-a")


def main():
    parser = argparse.ArgumentParser(description="YouTube Skill")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("accounts").set_defaults(func=cmd_accounts)

    login = subs.add_parser("login")
    login.add_argument("--account", "-a")
    login.set_defaults(func=cmd_login)

    logout = subs.add_parser("logout")
    logout.add_argument("--account", "-a")
    logout.set_defaults(func=cmd_logout)

    me = subs.add_parser("me")
    add_account_arg(me)
    me.set_defaults(func=cmd_me)

    channels = subs.add_parser("channels")
    add_account_arg(channels)
    channels.set_defaults(func=cmd_channels)

    videos = subs.add_parser("videos")
    videos.add_argument("--channel", "-c")
    videos.add_argument("--limit", "-l", type=int, default=20)
    add_account_arg(videos)
    videos.set_defaults(func=cmd_videos)

    video = subs.add_parser("video")
    video.add_argument("video_id")
    add_account_arg(video)
    video.set_defaults(func=cmd_video)

    search = subs.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", "-l", type=int, default=20)
    search.add_argument("--type", "-t", choices=["video", "channel", "playlist"], default="video")
    add_account_arg(search)
    search.set_defaults(func=cmd_search)

    playlists = subs.add_parser("playlists")
    playlists.add_argument("--channel", "-c")
    add_account_arg(playlists)
    playlists.set_defaults(func=cmd_playlists)

    playlist = subs.add_parser("playlist")
    playlist.add_argument("playlist_id")
    playlist.add_argument("--limit", "-l", type=int, default=50)
    add_account_arg(playlist)
    playlist.set_defaults(func=cmd_playlist)

    create_pl = subs.add_parser("create-playlist")
    create_pl.add_argument("--title", "-t", required=True)
    create_pl.add_argument("--description", "-d")
    create_pl.add_argument("--privacy", choices=["public", "private", "unlisted"], default="private")
    add_account_arg(create_pl)
    create_pl.set_defaults(func=cmd_create_playlist)

    add_to_pl = subs.add_parser("add-to-playlist")
    add_to_pl.add_argument("playlist_id")
    add_to_pl.add_argument("--video", "-v", required=True)
    add_account_arg(add_to_pl)
    add_to_pl.set_defaults(func=cmd_add_to_playlist)

    rm_from_pl = subs.add_parser("remove-from-playlist")
    rm_from_pl.add_argument("playlist_item_id")
    add_account_arg(rm_from_pl)
    rm_from_pl.set_defaults(func=cmd_remove_from_playlist)

    comments = subs.add_parser("comments")
    comments.add_argument("video_id")
    comments.add_argument("--limit", "-l", type=int, default=20)
    add_account_arg(comments)
    comments.set_defaults(func=cmd_comments)

    comment = subs.add_parser("comment")
    comment.add_argument("video_id")
    comment.add_argument("--text", "-t", required=True)
    add_account_arg(comment)
    comment.set_defaults(func=cmd_comment)

    reply = subs.add_parser("reply")
    reply.add_argument("comment_id")
    reply.add_argument("--text", "-t", required=True)
    add_account_arg(reply)
    reply.set_defaults(func=cmd_reply)

    subscriptions = subs.add_parser("subscriptions")
    add_account_arg(subscriptions)
    subscriptions.set_defaults(func=cmd_subscriptions)

    subscribe = subs.add_parser("subscribe")
    subscribe.add_argument("channel_id")
    add_account_arg(subscribe)
    subscribe.set_defaults(func=cmd_subscribe)

    unsubscribe = subs.add_parser("unsubscribe")
    unsubscribe.add_argument("subscription_id")
    add_account_arg(unsubscribe)
    unsubscribe.set_defaults(func=cmd_unsubscribe)

    upload = subs.add_parser("upload")
    upload.add_argument("--file", "-f", required=True)
    upload.add_argument("--title", "-t", required=True)
    upload.add_argument("--description", "-d")
    upload.add_argument("--privacy", choices=["public", "private", "unlisted"], default="private")
    add_account_arg(upload)
    upload.set_defaults(func=cmd_upload)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
