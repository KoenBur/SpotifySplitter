const previewData = document.querySelector("#preview-tracks");
const previewResults = document.querySelector(".preview-results");
const previewGroups = document.querySelector("#preview-groups");
const trackLimit = document.querySelector("#track-limit");
const groupCount = document.querySelector("#group-count");
const groupCountLabel = document.querySelector("#group-count-label");
const genreNote = document.querySelector("#genre-note");
const modeButtons = document.querySelectorAll(".mode-button");
const genreDetail = document.querySelector("#genre-detail");
const genreDetailControl = document.querySelector("#genre-detail-control");

const DETAIL_NAMES = ["Broadest", "Broad", "Balanced", "Specific", "Most specific"];

const POPULARITY_TIERS = [
  [100_000_000, "Smash hits", "100M+ plays"],
  [10_000_000, "Popular", "10M–100M plays"],
  [1_000_000, "Well known", "1M–10M plays"],
  [0, "Deep cuts", "Under 1M plays"],
];

function formatDuration(ms) {
  const minutes = Math.round(ms / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
}

if (previewData && previewGroups) {
  const tracks = JSON.parse(previewData.textContent);
  const playlistId = previewResults.dataset.playlistId;
  let mode = "count";
  let genreGroups;
  const genreRequests = new Map();

  function appendTrack(group, track) {
    const row = document.createElement("a");
    row.className = "track-row";
    row.href = track.url;
    row.target = "_blank";
    row.rel = "noreferrer";

    if (track.image) {
      const image = document.createElement("img");
      image.src = track.image;
      image.alt = "";
      image.loading = "lazy";
      row.append(image);
    }

    const details = document.createElement("span");
    details.className = "track-details";
    const title = document.createElement("strong");
    title.textContent = track.name;
    const artist = document.createElement("span");
    artist.textContent = track.artists.join(", ");
    details.append(title, artist);
    row.append(details);
    group.append(row);
  }

  function copyButton(groupTracks) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button copy-button";
    button.textContent = "Copy links";
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(groupTracks.map((track) => track.url).join("\n"));
        button.textContent = "Copied";
      } catch {
        button.textContent = "Copy failed";
      }
      setTimeout(() => { button.textContent = "Copy links"; }, 2000);
    });
    return button;
  }

  function renderGroups(groups, label) {
    previewGroups.replaceChildren();
    for (const { name, detail, tracks: groupTracks } of groups) {
      const group = document.createElement("section");
      group.className = "preview-group";
      const heading = document.createElement("div");
      heading.className = "preview-group-heading";
      const title = document.createElement("h3");
      title.textContent = name;
      const count = document.createElement("span");
      const duration = groupTracks.reduce((total, track) => total + (track.duration_ms || 0), 0);
      count.textContent = `${groupTracks.length} tracks · ${formatDuration(duration)}`;
      heading.append(title, count);
      group.append(heading);

      const meta = document.createElement("div");
      meta.className = "preview-group-meta";
      const detailText = document.createElement("span");
      detailText.textContent = detail || "";
      meta.append(detailText, copyButton(groupTracks));
      group.append(meta);

      groupTracks.forEach((track) => appendTrack(group, track));
      previewGroups.append(group);
    }
    groupCount.textContent = String(groups.length);
    groupCountLabel.textContent = label;
  }

  function renderCountGroups() {
    const limit = Math.max(1, Number(trackLimit.value) || 1);
    const groups = [];
    for (let start = 0; start < tracks.length; start += limit) {
      groups.push({
        name: `Part ${groups.length + 1}`,
        detail: `Tracks ${start + 1}–${Math.min(start + limit, tracks.length)}`,
        tracks: tracks.slice(start, start + limit),
      });
    }
    renderGroups(groups, "parts");
  }

  function renderArtistGroups() {
    const byArtist = new Map();
    for (const track of tracks) {
      const artist = track.artists[0] || "Unknown artist";
      if (!byArtist.has(artist)) byArtist.set(artist, []);
      byArtist.get(artist).push(track);
    }
    const minimum = tracks.length >= 40 ? 3 : 2;
    const groups = [];
    const various = [];
    for (const [artist, artistTracks] of byArtist) {
      if (artistTracks.length >= minimum) groups.push({ name: artist, tracks: artistTracks });
      else various.push(...artistTracks);
    }
    groups.sort((left, right) => right.tracks.length - left.tracks.length);
    if (various.length) {
      groups.push({ name: "Various artists", detail: `Artists with fewer than ${minimum} tracks`, tracks: various });
    }
    renderGroups(groups, "artist groups");
  }

  function renderPopularityGroups() {
    const groups = POPULARITY_TIERS.map(([, name, detail]) => ({ name, detail, tracks: [] }));
    const unknown = [];
    for (const track of tracks) {
      if (track.play_count == null) {
        unknown.push(track);
        continue;
      }
      const tier = POPULARITY_TIERS.findIndex(([minimum]) => track.play_count >= minimum);
      groups[tier].tracks.push(track);
    }
    const shown = groups.filter((group) => group.tracks.length);
    shown.forEach((group) => group.tracks.sort((left, right) => right.play_count - left.play_count));
    if (unknown.length) shown.push({ name: "Unknown", detail: "Spotify shared no play count", tracks: unknown });
    renderGroups(shown, "popularity tiers");
  }

  function renderAddedGroups() {
    const byYear = new Map();
    for (const track of tracks) {
      const year = track.added_at ? track.added_at.slice(0, 4) : "Unknown";
      if (!byYear.has(year)) byYear.set(year, []);
      byYear.get(year).push(track);
    }
    const groups = [...byYear.entries()]
      .sort(([left], [right]) => right.localeCompare(left))
      .map(([year, yearTracks]) => ({ name: year === "Unknown" ? "Date unknown" : `Added in ${year}`, tracks: yearTracks }));
    renderGroups(groups, "years");
  }

  function renderGenreGroups() {
    const byUri = new Map();
    for (const track of tracks) {
      if (!byUri.has(track.uri)) byUri.set(track.uri, []);
      byUri.get(track.uri).push(track);
    }
    const groups = genreGroups.groups.map((group) => ({
      name: group.name,
      detail: group.genres.slice(1).join(" · "),
      tracks: [...new Set(group.uris)].flatMap((uri) => byUri.get(uri) || []),
    }));
    renderGroups(groups, "genre groups");
  }

  function requestGenres(detail) {
    if (!genreRequests.has(detail)) {
      const url = `/api/playlists/${encodeURIComponent(playlistId)}/genres?detail=${detail}`;
      genreRequests.set(detail, fetch(url).then(async (response) => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || "The genre lookup didn't complete. Please try again.");
        return result;
      }, () => {
        throw new Error("We couldn't reach the server for the genre lookup. Please try again.");
      }));
    }
    return genreRequests.get(detail);
  }

  async function showGenres() {
    const detail = Number(genreDetail.value);
    genreDetail.setAttribute("aria-valuetext", DETAIL_NAMES[detail - 1]);
    genreNote.hidden = false;
    genreNote.textContent = genreGroups
      ? "Regrouping…"
      : "Looking up artist genres on MusicBrainz… Large playlists can take up to a minute.";
    if (!genreGroups) {
      previewGroups.replaceChildren();
      groupCount.textContent = "–";
      groupCountLabel.textContent = "genre groups";
    }
    try {
      const result = await requestGenres(detail);
      if (mode !== "genre" || Number(genreDetail.value) !== detail) return;
      genreGroups = result;
      genreNote.textContent = `Genres found for ${result.artists_with_genres} of ${result.artists} artists, `
        + "from MusicBrainz tags and related artists on Spotify. Treat the groups as suggestions.";
      renderGenreGroups();
    } catch (error) {
      genreRequests.delete(detail);
      if (mode === "genre" && Number(genreDetail.value) === detail) genreNote.textContent = error.message;
    }
  }

  const renderers = {
    count: renderCountGroups,
    artist: renderArtistGroups,
    popularity: renderPopularityGroups,
    added: renderAddedGroups,
  };

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      mode = button.dataset.mode;
      modeButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      trackLimit.closest(".track-limit-control").hidden = mode !== "count";
      genreDetailControl.hidden = mode !== "genre";
      if (mode === "genre") {
        showGenres();
      } else {
        genreNote.hidden = true;
        renderers[mode]();
      }
    });
  });

  trackLimit.addEventListener("input", () => {
    if (mode === "count") renderCountGroups();
  });

  genreDetail.addEventListener("change", () => {
    if (mode === "genre") showGenres();
  });

  renderCountGroups();
}
