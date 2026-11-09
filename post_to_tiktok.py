"""Compliant TikTok auto-poster using the OFFICIAL TikTok Content Posting API.

This script posts a video that YOU OWN to YOUR OWN TikTok account, through
TikTok's official Content Posting API, after the account holder has authorized
your developer app via OAuth. It is the same mechanism legitimate schedulers
(Buffer, Hootsuite, Postiz, ...) use.

What this script is NOT:
  * It does NOT automate the TikTok app/website with a headless browser or
    reverse-engineered endpoints (that violates TikTok's Terms of Service).
  * It does NOT create accounts, buy/inflate followers, or perform any
    engagement on other people's content.

Hard facts about the API (verify against current docs before shipping):
  * Endpoints live under https://open.tiktokapis.com/v2/...
  * Scopes required: `video.upload` and/or `video.publish`.
  * Access tokens expire ~24h; refresh with your refresh_token.
  * UNAUDITED apps can only post with privacy_level = SELF_ONLY (private).
    Public posting requires passing TikTok's app audit.
  * Per-creator daily publish cap is small (~15/day). Respect it.
  * You must let users disclose commercial/branded content.

Docs:
  https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
  https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content

Setup:
  1. Create an app at https://developers.tiktok.com and add the Content Posting
     API product; request the video.upload / video.publish scopes.
  2. Set redirect URI(s) for OAuth.
  3. Put credentials in env vars:  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET
  4. Run the one-time consent flow to get an access token (see build_auth_url
     + exchange_code_for_token), then pass --access-token to post.

Install:  pip install requests
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, Optional
from urllib.parse import urlencode

import requests

API_BASE = "https://open.tiktokapis.com"
AUTH_BASE = "https://www.tiktok.com/v2/auth/authorize/"

MB = 1024 * 1024
MAX_SINGLE_CHUNK = 64 * MB  # files <= this can be sent as one chunk


# ---------------------------------------------------------------------------
# Config (.env loader)
# ---------------------------------------------------------------------------
def _load_dotenv(path: Optional[str] = None) -> None:
    """Minimal .env loader (no external dependency).

    Reads ``KEY=VALUE`` lines from ``tiktok_poster/.env`` and sets them in
    os.environ, but only for keys not already present in the real environment
    (so real env vars always win). Lines starting with ``#`` are comments.
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# OAuth (one-time user consent)
# ---------------------------------------------------------------------------
def build_auth_url(client_key: str, redirect_uri: str, state: str = "state123") -> str:
    """URL to open in a browser so the account owner can authorize the app."""
    params = {
        "client_key": client_key,
        "scope": "video.upload,video.publish",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_BASE}?{urlencode(params)}"


def exchange_code_for_token(
    client_key: str, client_secret: str, code: str, redirect_uri: str
) -> Dict:
    """Exchange the authorization `code` (from the redirect) for tokens."""
    resp = requests.post(
        f"{API_BASE}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> Dict:
    resp = requests.post(
        f"{API_BASE}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Content Posting API - Direct Post (FILE_UPLOAD)
# ---------------------------------------------------------------------------
def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def query_creator_info(access_token: str) -> Dict:
    """Required before publishing: returns allowed privacy levels, nickname, etc."""
    resp = requests.post(
        f"{API_BASE}/v2/post/publish/creator_info/query/",
        headers=_auth_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _plan_chunks(video_size: int) -> Dict[str, int]:
    """Decide chunk_size / total_chunk_count for the upload.

    Short TikTok clips are almost always under 64 MB and go as a single chunk.
    Larger files are split; the final chunk carries any remainder.
    """
    if video_size <= MAX_SINGLE_CHUNK:
        return {"chunk_size": video_size, "total_chunk_count": 1}
    chunk_size = MAX_SINGLE_CHUNK
    total = video_size // chunk_size  # last chunk absorbs the remainder
    return {"chunk_size": chunk_size, "total_chunk_count": max(1, total)}


def init_direct_post(
    access_token: str,
    title: str,
    video_size: int,
    chunk_size: int,
    total_chunk_count: int,
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    is_commercial: bool = False,
    is_your_brand: bool = False,
    is_branded_content: bool = False,
) -> Dict:
    """Initialize a Direct Post. Returns publish_id and the upload_url."""
    post_info = {
        "title": title,
        "privacy_level": privacy_level,
        "disable_comment": disable_comment,
        "disable_duet": disable_duet,
        "disable_stitch": disable_stitch,
    }
    # Commercial-content disclosure (required when the post promotes something).
    if is_commercial:
        post_info["brand_organic_toggle"] = is_your_brand
        post_info["brand_content_toggle"] = is_branded_content

    payload = {
        "post_info": post_info,
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }
    resp = requests.post(
        f"{API_BASE}/v2/post/publish/video/init/",
        headers=_auth_headers(access_token),
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        # Surface the common unaudited-app error clearly.
        raise RuntimeError(f"init failed ({resp.status_code}): {resp.text}")
    return resp.json()


def upload_file(upload_url: str, file_path: str, video_size: int,
                chunk_size: int, total_chunk_count: int) -> None:
    """PUT the video bytes to the upload_url using Content-Range per chunk."""
    with open(file_path, "rb") as fh:
        for i in range(total_chunk_count):
            start = i * chunk_size
            # Last chunk takes everything that remains.
            end = video_size - 1 if i == total_chunk_count - 1 else start + chunk_size - 1
            fh.seek(start)
            data = fh.read(end - start + 1)
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{video_size}",
            }
            r = requests.put(upload_url, headers=headers, data=data, timeout=120)
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"chunk {i} upload failed ({r.status_code}): {r.text}")


def fetch_status(access_token: str, publish_id: str) -> Dict:
    resp = requests.post(
        f"{API_BASE}/v2/post/publish/status/fetch/",
        headers=_auth_headers(access_token),
        json={"publish_id": publish_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def post_video(
    access_token: str,
    file_path: str,
    title: str,
    privacy_level: str = "SELF_ONLY",
    poll: bool = True,
) -> Dict:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)
    video_size = os.path.getsize(file_path)
    plan = _plan_chunks(video_size)

    # Best practice: confirm the creator can post before uploading.
    info = query_creator_info(access_token)
    print("creator_info:", info.get("data", {}).get("creator_nickname", "<unknown>"))

    init = init_direct_post(
        access_token, title, video_size,
        plan["chunk_size"], plan["total_chunk_count"],
        privacy_level=privacy_level,
    )
    data = init.get("data", {})
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not publish_id or not upload_url:
        raise RuntimeError(f"unexpected init response: {init}")
    print("publish_id:", publish_id)

    upload_file(upload_url, file_path, video_size,
                plan["chunk_size"], plan["total_chunk_count"])
    print("upload complete; TikTok is now processing the video")

    if poll:
        for _ in range(20):
            time.sleep(3)
            status = fetch_status(access_token, publish_id).get("data", {})
            state = status.get("status")
            print("status:", state)
            if state in ("PUBLISH_COMPLETE", "FAILED"):
                return status
    return {"publish_id": publish_id}


def main(argv=None) -> int:
    _load_dotenv()  # load tiktok_poster/.env if present

    p = argparse.ArgumentParser(description="Post a video to your own TikTok via the official API.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auth-url", help="Print the OAuth consent URL to open in a browser.")
    a.add_argument("--redirect-uri", default=None, help="Defaults to TIKTOK_REDIRECT_URI from .env")

    t = sub.add_parser("token", help="Exchange an authorization code for tokens.")
    t.add_argument("--code", required=True)
    t.add_argument("--redirect-uri", default=None, help="Defaults to TIKTOK_REDIRECT_URI from .env")

    post = sub.add_parser("post", help="Upload and publish a video you own.")
    post.add_argument("--access-token", default=None, help="Defaults to TIKTOK_ACCESS_TOKEN from .env")
    post.add_argument("--file", required=True, help="Path to your .mp4")
    post.add_argument("--title", default="")
    post.add_argument("--privacy", default="SELF_ONLY",
                      help="SELF_ONLY (default). PUBLIC_TO_EVERYONE needs an audited app.")

    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    # Credentials/config come from the environment (populated from .env above).
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    env_redirect = os.environ.get("TIKTOK_REDIRECT_URI", "")
    env_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")

    if args.cmd == "auth-url":
        redirect_uri = args.redirect_uri or env_redirect
        if not client_key or not redirect_uri:
            print("Need TIKTOK_CLIENT_KEY and a redirect URI "
                  "(set TIKTOK_REDIRECT_URI in .env or pass --redirect-uri).", file=sys.stderr)
            return 1
        print(build_auth_url(client_key, redirect_uri))
        return 0

    if args.cmd == "token":
        redirect_uri = args.redirect_uri or env_redirect
        if not client_key or not client_secret or not redirect_uri:
            print("Need TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and a redirect URI.", file=sys.stderr)
            return 1
        tok = exchange_code_for_token(client_key, client_secret, args.code, redirect_uri)
        print(tok)
        return 0

    if args.cmd == "post":
        access_token = args.access_token or env_token
        if not access_token:
            print("Need an access token (set TIKTOK_ACCESS_TOKEN in .env or pass --access-token).",
                  file=sys.stderr)
            return 1
        result = post_video(access_token, args.file, args.title, args.privacy)
        print("result:", result)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
