# SpotifySplitter

A small Flask website that loads any public Spotify playlist and suggests ways to split it: by genre, artist, popularity, date added or a fixed number of tracks. No Spotify account, developer app or sign-in is needed, and nothing is ever written back to Spotify.

## Requirements

- Python 3.10 or newer

## Run locally

On Windows, double-click `start.bat`. It sets everything up the first time, starts the site and opens it in your browser. Close its window to stop the site.

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

5. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) and paste a playlist link.

## Build a Windows app

Double-click `build.bat` to build `dist\SpotifySplitter.exe`, a single file that runs on any Windows PC without Python. It opens SpotifySplitter in its own app window (using Windows' built-in Edge WebView2); closing the window stops it. Links to Spotify open in your browser or the Spotify app. To try the app window without building, run `python app.py --window`.

Rebuild after changing the code. Pushing a version tag (for example `git tag v1.1.0` then `git push origin v1.1.0`) makes GitHub build the `.exe` and publish it under Releases. An optional `.env` goes next to the `.exe`. The `.exe` isn't signed, so Windows SmartScreen may warn the first time you open it; choose **More info** → **Run anyway**.

## How it works

Playlists are read from Spotify's public web player data with [SpotifyScraper](https://github.com/AliAkhtari78/SpotifyScraper), the same data anyone can see on open.spotify.com without logging in. Private playlists can't be loaded. Large playlists are capped at the first 1,500 tracks.

Spotify's public data has no genres, so the genre split looks artists up on [MusicBrainz](https://musicbrainz.org/), the community music database, through the Spotify links stored there. Artists MusicBrainz doesn't know borrow genres from their related artists on Spotify. Artists are then clustered by genre profile and every group is named after the genre that sets it apart. Results are suggestions, and the first lookup for a large playlist can take up to a minute because MusicBrainz allows one request per second.

To turn a group into a real playlist, press **Copy links**, create an empty playlist in the Spotify desktop app, click into it and paste.

Playlists and genre results are cached in memory for 30 minutes.
