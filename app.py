import logging
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from spotify_scraper import NotFoundError, RateLimitedError, SpotifyClient, SpotifyScraperError

import genres

# Built as an .exe, bundled files are unpacked to a temporary folder, while
# .env lives next to the .exe itself.
FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
HOME_DIR = os.path.dirname(sys.executable) if FROZEN else BUNDLE_DIR

load_dotenv(os.path.join(HOME_DIR, ".env"))

app = Flask(
    __name__,
    template_folder=os.path.join(BUNDLE_DIR, "templates"),
    static_folder=os.path.join(BUNDLE_DIR, "static"),
)

MAX_TRACKS = 1500
CACHE_SECONDS = 30 * 60
PLAYLIST_ID = re.compile(r"[A-Za-z0-9]{22}")

_cache = {}
_cache_lock = threading.Lock()


def parse_playlist_link(value):
    value = value.strip()
    if value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) == 3 and parts[1] == "playlist" and PLAYLIST_ID.fullmatch(parts[2]):
            return parts[2]
        raise ValueError("Paste a Spotify playlist link.")
    if PLAYLIST_ID.fullmatch(value):
        return value

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"open.spotify.com", "play.spotify.com"}:
        raise ValueError("Paste a playlist link from open.spotify.com.")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and re.fullmatch(r"intl-[a-z]{2}", segments[0], re.IGNORECASE):
        segments = segments[1:]
    if len(segments) >= 2 and segments[0] == "playlist" and PLAYLIST_ID.fullmatch(segments[1]):
        return segments[1]
    raise ValueError("That Spotify link isn't a playlist.")


def _cached(playlist_id):
    with _cache_lock:
        entry = _cache.get(playlist_id)
        if entry and time.monotonic() - entry["loaded"] < CACHE_SECONDS:
            return entry
        _cache.pop(playlist_id, None)
        return None


def _image(images, size=300):
    if not images:
        return None
    return min(images, key=lambda image: abs((image.width or size) - size)).url


def load_playlist(playlist_id):
    entry = _cached(playlist_id)
    if entry:
        return entry["playlist"]

    with SpotifyClient() as client:
        source = client.get_playlist(playlist_id, max_tracks=MAX_TRACKS)

    tracks = []
    for item in source.tracks:
        track = item.track
        artists = [artist for artist in track.artists if artist.uri.startswith("spotify:artist:")]
        tracks.append({
            "uri": track.uri,
            "name": track.name,
            "artists": [artist.name for artist in track.artists],
            "artist_ids": [artist.uri.rsplit(":", 1)[-1] for artist in artists],
            "album": track.album.name if track.album else None,
            "image": _image(track.images),
            "url": track.url,
            "duration_ms": track.duration_ms,
            "play_count": track.play_count,
            "added_at": item.added_at.isoformat() if item.added_at else None,
        })

    playlist = {
        "id": playlist_id,
        "name": source.name,
        "owner": source.owner.name if source.owner else None,
        "url": source.url,
        "image": _image(source.images, 640),
        "total_tracks": source.total_tracks or len(tracks),
        "tracks": tracks,
    }
    with _cache_lock:
        if len(_cache) >= 50:
            _cache.pop(min(_cache, key=lambda key: _cache[key]["loaded"]))
        _cache[playlist_id] = {"loaded": time.monotonic(), "playlist": playlist, "genres": None}
    return playlist


@app.get("/")
def index():
    link = request.args.get("playlist", "").strip()
    if not link:
        return render_template("index.html", preview=None, error=None, link="")

    error = None
    try:
        preview = load_playlist(parse_playlist_link(link))
        if not preview["tracks"]:
            error = "That playlist doesn't contain any tracks we can preview."
    except ValueError as exc:
        error = str(exc)
    except NotFoundError:
        error = "We couldn't find that playlist. It may be private or deleted; only public playlists can be loaded."
    except RateLimitedError:
        error = "Spotify is receiving too many requests right now. Wait a little and try again."
    except SpotifyScraperError as exc:
        app.logger.warning("Loading playlist failed: %s", exc)
        error = "We couldn't load that playlist from Spotify. Please try again."

    if error:
        return render_template("index.html", preview=None, error=error, link=link)
    return render_template("index.html", preview=preview, error=None, link=link)


@app.get("/api/playlists/<playlist_id>/genres")
def playlist_genres(playlist_id):
    entry = _cached(playlist_id) if PLAYLIST_ID.fullmatch(playlist_id) else None
    if not entry:
        return jsonify(error="Load the playlist again before looking up genres."), 404
    if entry["genres"] is None:
        try:
            entry["genres"] = genres.suggest_genre_groups(entry["playlist"]["tracks"])
        except (httpx.HTTPError, SpotifyScraperError) as exc:
            app.logger.warning("Genre lookup failed: %s", exc)
            return jsonify(error="The genre lookup didn't complete. Please try again in a moment."), 502
    return jsonify(entry["genres"])


def run_desktop(host="127.0.0.1", port=5000):
    """Start the site and open it in the browser; reuse a copy that's already running."""
    url = f"http://{host}:{port}/"
    with socket.socket() as probe:
        already_running = probe.connect_ex((host, port)) == 0
    if already_running:
        webbrowser.open(url)
        return

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print("SpotifySplitter is running at", url)
    print("Keep this window open while you use it; close it to stop SpotifySplitter.")
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    if FROZEN:
        run_desktop()
    else:
        app.run(debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)
