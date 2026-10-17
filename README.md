# SpotifySplitter

A small Flask website that loads any public Spotify playlist and suggests ways to split it: by genre, artist, popularity, date added or a fixed number of tracks. No Spotify account, developer app or sign-in is needed, and nothing is ever written back to Spotify.

> **Disclaimer:** SpotifySplitter is an independent hobby project. It is not affiliated with, endorsed by or sponsored by Spotify AB. Spotify is a trademark of Spotify AB. The app reads publicly visible playlist data from Spotify's web player, which Spotify's terms of use may not permit; use it at your own risk and for personal use.

## Requirements

- Python 3.10 or newer

## Run locally

On Windows run: `start.bat`

To set it up by hand instead:

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Optionally create a `.env` file containing `MUSICBRAINZ_CONTACT=` followed by an email address or URL. MusicBrainz asks API clients to identify themselves this way.

4. Start the site:

   ```powershell
   python app.py
   ```

## How it works

Playlists are read from Spotify's public web player data with [SpotifyScraper](https://github.com/AliAkhtari78/SpotifyScraper), the same data anyone can see on open.spotify.com without logging in. Private playlists can't be loaded. Large playlists are capped at the first 1,500 tracks.

Spotify's public data has no genres, so the genre split looks artists up on [MusicBrainz](https://musicbrainz.org/), the community music database, through the Spotify links stored there. Artists MusicBrainz doesn't know borrow genres from their related artists on Spotify. Artists are then clustered by genre profile and every group is named after the genre that sets it apart. Results are suggestions, and the first lookup for a large playlist can take up to a minute because MusicBrainz allows one request per second.

To turn a group into a real playlist, press **Copy links**, create an empty playlist in the Spotify desktop app, click into it and paste.

Playlists and genre results are cached in memory for 30 minutes.

## License

[MIT](LICENSE)
