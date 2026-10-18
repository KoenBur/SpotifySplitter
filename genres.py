"""Genre suggestions for playlist tracks.

Spotify's public pages carry no genre data, so artist genres come from
MusicBrainz community tags, matched through the Spotify artist links stored in
MusicBrainz. Artists MusicBrainz doesn't know borrow the genres of their
Spotify related artists.

Artists are then clustered by genre profile, and each cluster is named after
the genre that sets it apart from the other clusters.
"""

import asyncio
import heapq
import math
import os
import re
import threading
import time
from collections import Counter, defaultdict
from typing import NamedTuple

import httpx
from spotify_scraper import AsyncSpotifyClient, RateLimit, SpotifyScraperError

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/"
MUSICBRAINZ_BATCH = 100
SPOTIFY_PARTNER_HOST = "api-partner.spotify.com"
RELATED_FOR_GENRES = 6
MAX_INFERRED_ARTISTS = 150
ACRONYMS = {"r&b", "edm", "idm", "ebm", "uk", "dnb"}


class DetailLevel(NamedTuple):
    merge_similarity: float  # stop merging clusters below this similarity
    max_groups: int  # ...unless there are more groups than this
    min_share: float  # smallest group, as a share of the playlist
    min_tracks: int  # smallest group, in tracks
    attach_similarity: float  # small clusters join the group whose profile is at least this similar
    broaden: float  # credit "pop rock" gives to "pop" and "rock"
    rarity: float  # how much genres shared by most of the playlist are weighed down


DETAIL_LEVELS = {
    1: DetailLevel(0.25, 5, 0.06, 4, 0.10, 0.6, 0.0),
    2: DetailLevel(0.35, 8, 0.04, 3, 0.10, 0.5, 0.3),
    3: DetailLevel(0.45, 12, 0.02, 3, 0.10, 0.4, 0.6),
    4: DetailLevel(0.55, 20, 0.015, 3, 0.15, 0.25, 0.8),
    5: DetailLevel(0.65, 30, 0.008, 2, 0.20, 0.15, 1.0),
}
DEFAULT_DETAIL = 3


def _user_agent():
    contact = os.getenv("MUSICBRAINZ_CONTACT", "").strip()
    return f"SpotifySplitter/1.0 ( {contact} )" if contact else "SpotifySplitter/1.0"


class MusicBrainz:
    """Rate-limited MusicBrainz client with an in-memory genre cache.

    MusicBrainz allows one request per second per client, so every request
    goes through one lock, shared by all web requests.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._genre_names = None
        self._artist_genres = {}

    def _get(self, path, params):
        with self._lock:
            for attempt in range(3):
                wait = self._last_request + 1.1 - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                response = httpx.get(
                    MUSICBRAINZ_API + path,
                    params=params,
                    headers={"User-Agent": _user_agent(), "Accept": "application/json"},
                    timeout=30,
                )
                self._last_request = time.monotonic()
                if response.status_code != 503:
                    break
                time.sleep(2 * (attempt + 1))
            return response

    def genre_names(self):
        if self._genre_names is None:
            response = self._get("genre/all", {"fmt": "txt"})
            response.raise_for_status()
            self._genre_names = {line.strip().lower() for line in response.text.splitlines() if line.strip()}
        return self._genre_names

    def artist_genres(self, spotify_ids):
        """Return ``{spotify_artist_id: {genre: weight}}`` for the given artists.

        Weights run from 0 to 1, relative to the artist's most-tagged genre.
        Artists MusicBrainz doesn't know map to an empty dict.
        """
        known_genres = self.genre_names()
        missing = [artist_id for artist_id in dict.fromkeys(spotify_ids) if artist_id not in self._artist_genres]
        for start in range(0, len(missing), MUSICBRAINZ_BATCH):
            batch = missing[start:start + MUSICBRAINZ_BATCH]
            mbids = self._musicbrainz_ids(batch)
            tags_by_mbid = self._artist_tags(set(mbids.values())) if mbids else {}
            for artist_id in batch:
                tags = tags_by_mbid.get(mbids.get(artist_id), [])
                counts = {tag["name"].lower(): tag.get("count", 0) for tag in tags}
                counts = {genre: count for genre, count in counts.items() if genre in known_genres and count > 0}
                top = max(counts.values(), default=0)
                ranked = sorted(counts.items(), key=lambda item: -item[1])[:6]
                self._artist_genres[artist_id] = {genre: count / top for genre, count in ranked}
        return {artist_id: self._artist_genres[artist_id] for artist_id in spotify_ids}

    def _musicbrainz_ids(self, spotify_ids):
        params = [("resource", f"https://open.spotify.com/artist/{artist_id}") for artist_id in spotify_ids]
        response = self._get("url", params + [("inc", "artist-rels"), ("fmt", "json")])
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        data = response.json()
        mbids = {}
        for url in data.get("urls", [data]):
            artist_id = url.get("resource", "").rstrip("/").rsplit("/", 1)[-1]
            artists = [rel["artist"]["id"] for rel in url.get("relations", []) if rel.get("target-type") == "artist"]
            if artist_id and artists:
                mbids[artist_id] = artists[0]
        return mbids

    def _artist_tags(self, mbids):
        query = " OR ".join(f"arid:{mbid}" for mbid in mbids)
        response = self._get("artist", {"query": query, "limit": 100, "fmt": "json"})
        response.raise_for_status()
        return {artist["id"]: artist.get("tags", []) for artist in response.json().get("artists", [])}


musicbrainz = MusicBrainz()
_related_cache = {}


async def _fetch_related(artist_ids):
    rate_limits = {SPOTIFY_PARTNER_HOST: RateLimit(per_second=10, burst=10)}
    async with AsyncSpotifyClient(host_rate_limits=rate_limits) as client:
        semaphore = asyncio.Semaphore(10)

        async def fetch(artist_id):
            async with semaphore:
                try:
                    related = await client.get_related_artists(artist_id)
                except SpotifyScraperError:
                    return artist_id, []
            return artist_id, [artist.id for artist in related if artist.id]

        return dict(await asyncio.gather(*(fetch(artist_id) for artist_id in artist_ids)))


def related_artists(artist_ids):
    """Return ``{artist_id: [related_artist_id, ...]}``, most related first."""
    missing = [artist_id for artist_id in artist_ids if artist_id not in _related_cache]
    if missing:
        _related_cache.update(asyncio.run(_fetch_related(missing)))
    return {artist_id: _related_cache[artist_id] for artist_id in artist_ids}


def collect_artist_genres(artist_ids):
    """Return ``(artist_genres, related)`` for the given artists.

    ``artist_genres`` maps every artist to ``{genre: weight}``; artists without
    MusicBrainz genres borrow them from their related artists. ``related``
    holds the related artists fetched for those artists.
    """
    artist_genres = musicbrainz.artist_genres(artist_ids)
    unknown = [artist_id for artist_id in artist_ids if not artist_genres[artist_id]][:MAX_INFERRED_ARTISTS]
    if not unknown:
        return artist_genres, {}

    related = related_artists(unknown)
    lookups = list(dict.fromkeys(rel for ids in related.values() for rel in ids[:RELATED_FOR_GENRES]))
    related_genres = musicbrainz.artist_genres(lookups)
    for artist_id in unknown:
        sources = [related_genres[rel] for rel in related[artist_id][:RELATED_FOR_GENRES] if related_genres[rel]]
        borrowed = Counter()
        for genres in sources:
            for genre, weight in genres.items():
                borrowed[genre] += 0.8 * weight / len(sources)
        artist_genres[artist_id] = dict(borrowed)
    return artist_genres, related


def _broaden(genres, known_genres, share):
    """Give broad genres partial credit, so "pop rock" also counts toward "pop" and "rock"."""
    broadened = Counter()
    for genre, weight in genres.items():
        broadened[genre] += weight
        words = re.split(r"[\s-]+", genre)
        for size in range(1, len(words)):
            for start in range(len(words) - size + 1):
                part = " ".join(words[start:start + size])
                if part in known_genres and part != genre:
                    broadened[part] = max(broadened[part], share * weight)
    return broadened


def _unit(vector):
    length = math.sqrt(sum(weight * weight for weight in vector.values()))
    return {genre: weight / length for genre, weight in vector.items()} if length else {}


def _cosine(left, right):
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(genre, 0) for genre, weight in left.items())


def _label(genre):
    label = " ".join(word.upper() if word in ACRONYMS else word for word in genre.split(" "))
    return label[0].upper() + label[1:]


def _cluster(profiles, sizes, min_size, level):
    """Average-linkage clustering of artist genre profiles, weighted by track count.

    Merging stops once no two clusters are similar enough, but continues past
    that point while there are more than ``level.max_groups`` clusters of
    ``min_size`` tracks or more. Returns ``(members, sizes)`` for the surviving
    clusters.
    """
    keys = list(profiles)
    members = {index: [key] for index, key in enumerate(keys)}
    sizes = {index: sizes[key] for index, key in enumerate(keys)}
    similarity = defaultdict(dict)
    heap = []
    for left in range(len(keys)):
        for right in range(left + 1, len(keys)):
            score = _cosine(profiles[keys[left]], profiles[keys[right]])
            if score > 0:
                similarity[left][right] = similarity[right][left] = score
                heap.append((-score, left, right))
    heapq.heapify(heap)

    alive = set(members)
    next_index = len(keys)
    while heap:
        score, left, right = heapq.heappop(heap)
        if left not in alive or right not in alive:
            continue
        large = sum(1 for index in alive if sizes[index] >= min_size)
        if -score < level.merge_similarity and large <= level.max_groups:
            break
        merged = next_index
        next_index += 1
        members[merged] = members.pop(left) + members.pop(right)
        sizes[merged] = sizes[left] + sizes[right]
        alive -= {left, right}
        for other in alive:
            score = (sizes[left] * similarity[left].get(other, 0) + sizes[right] * similarity[right].get(other, 0)) / sizes[merged]
            if score > 0:
                similarity[merged][other] = similarity[other][merged] = score
                heapq.heappush(heap, (-score, merged, other))
        alive.add(merged)
    return {index: members[index] for index in alive}, {index: sizes[index] for index in alive}


def _name_groups(groups, vectors):
    """Name each group after its most distinctive genre, without repeating names."""
    means = []
    for uris in groups:
        mean = Counter()
        for uri in uris:
            top = max(vectors[uri].values())
            for genre, weight in vectors[uri].items():
                mean[genre] += weight / top / len(uris)
        means.append(mean)

    # A genre describes a group well when it's common there and less common in
    # the group where it's next strongest.
    scores = []
    for index, mean in enumerate(means):
        strongest_elsewhere = Counter()
        for position, other in enumerate(means):
            if position != index:
                for genre, weight in other.items():
                    strongest_elsewhere[genre] = max(strongest_elsewhere[genre], weight)
        scores.append({genre: mean[genre] - 0.5 * strongest_elsewhere[genre] for genre in mean})
    rankings = [sorted(score, key=score.get, reverse=True) for score in scores]

    # Hand out names best fit first, so each genre goes to the group it suits most.
    names, used = [None] * len(groups), set()
    candidates = sorted(((score, index, genre) for index, score_by_genre in enumerate(scores)
                         for genre, score in score_by_genre.items()), reverse=True)
    for _, index, genre in candidates:
        if names[index] is None and genre not in used:
            names[index] = genre
            used.add(genre)
    names = [name or ranking[0] for name, ranking in zip(names, rankings)]
    return names, [[name] + [genre for genre in ranking if genre != name][:3] for name, ranking in zip(names, rankings)]


def suggest_genre_groups(tracks, detail=DEFAULT_DETAIL):
    """Suggest genre groups for tracks shaped like ``{"uri", "artist_ids"}``.

    ``detail`` runs from 1 (a few broad groups) to 5 (many specific ones).
    Returns the groups, largest first, followed by "Other genres" and
    "No genre found" groups for tracks that fit no suggestion.
    """
    level = DETAIL_LEVELS[detail]
    artist_ids = list(dict.fromkeys(artist_id for track in tracks for artist_id in track["artist_ids"]))
    artist_genres, related = collect_artist_genres(artist_ids)
    known_genres = musicbrainz.genre_names()

    vectors, tracks_by_artist, unknown_by_artist = {}, defaultdict(list), defaultdict(list)
    for track in tracks:
        vector = Counter()
        for position, artist_id in enumerate(track["artist_ids"]):
            for genre, weight in _broaden(artist_genres.get(artist_id, {}), known_genres, level.broaden).items():
                vector[genre] += (1.0 if position == 0 else 0.5) * weight
        primary = track["artist_ids"][0] if track["artist_ids"] else None
        if vector:
            vectors[track["uri"]] = vector
            tracks_by_artist[primary].append(track["uri"])
        else:
            unknown_by_artist[primary].append(track["uri"])

    profiles = {}
    for artist_id, uris in tracks_by_artist.items():
        total = Counter()
        for uri in uris:
            total.update(vectors[uri])
        profiles[artist_id] = total

    # Genres most of the playlist shares ("rock" in a rock playlist) say little
    # about how to split it, so specific levels weigh them down.
    spread = Counter(genre for profile in profiles.values() for genre in profile)
    rarity = {genre: math.log((1 + len(profiles)) / count) ** level.rarity for genre, count in spread.items()}
    profiles = {
        artist_id: _unit({genre: weight * rarity[genre] for genre, weight in profile.items()})
        for artist_id, profile in profiles.items()
    }

    min_size = max(level.min_tracks, round(len(tracks) * level.min_share))
    sizes = {artist_id: len(uris) for artist_id, uris in tracks_by_artist.items()}
    clusters, cluster_sizes = _cluster(profiles, sizes, min_size, level)

    def centroid(artist_list):
        total = Counter()
        for artist_id in artist_list:
            for genre, weight in profiles[artist_id].items():
                total[genre] += weight * sizes[artist_id]
        return _unit(total)

    large = [index for index in clusters if cluster_sizes[index] >= min_size]
    artists_in = {index: list(clusters[index]) for index in large}
    centroids = {index: centroid(clusters[index]) for index in large}
    leftover_artists = []
    for index in clusters:
        if index in large:
            continue
        # Small clusters join the group whose overall genre profile they resemble most.
        own = centroid(clusters[index])
        best = max(large, key=lambda other: _cosine(own, centroids[other]), default=None)
        if best is not None and _cosine(own, centroids[best]) >= level.attach_similarity:
            artists_in[best] += clusters[index]
        else:
            leftover_artists += clusters[index]

    # Artists without any genre join the group holding most of their related artists.
    cluster_of = {artist_id: index for index, artist_list in artists_in.items() for artist_id in artist_list}
    no_genre = []
    for artist_id, uris in unknown_by_artist.items():
        votes = Counter(cluster_of[rel] for rel in related.get(artist_id, []) if rel in cluster_of)
        if votes:
            artists_in[votes.most_common(1)[0][0]].append(artist_id)
        else:
            no_genre += uris

    groups = []
    for artist_list in artists_in.values():
        groups.append([uri for artist_id in artist_list for uri in tracks_by_artist.get(artist_id, []) + unknown_by_artist.get(artist_id, [])])
    groups.sort(key=len, reverse=True)
    names, top_genres = _name_groups([[uri for uri in uris if uri in vectors] for uris in groups], vectors)

    result = [
        {"name": _label(name), "genres": [_label(genre) for genre in genres], "uris": uris}
        for name, genres, uris in zip(names, top_genres, groups)
    ]
    other = [uri for artist_id in leftover_artists for uri in tracks_by_artist[artist_id]]
    if other:
        result.append({"name": "Other genres", "genres": [], "uris": other})
    if no_genre:
        result.append({"name": "No genre found", "genres": [], "uris": no_genre})
    return {
        "groups": result,
        "detail": detail,
        "artists": len(artist_ids),
        "artists_with_genres": sum(1 for artist_id in artist_ids if artist_genres.get(artist_id)),
    }
