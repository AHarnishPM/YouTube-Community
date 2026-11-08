// Everything drawn on the YouTube player: the comment overlay, a status line, markers above the progress bar,
// and an on/off button in the player controls.

const OVERLAY_LEAD_SECONDS = 2.5;
const OVERLAY_LINGER_SECONDS = 5.5;
// Longer comments stay up to this many extra seconds, about 1 second per 40 characters.
const OVERLAY_MAX_EXTRA_LINGER_SECONDS = 5;
const OVERLAY_MAX_VISIBLE = 3;
const OVERLAY_FADE_MS = 300;
const MARKER_BUCKETS = 150;
const SVG_NS = "http://www.w3.org/2000/svg";

let settings = { ...DEFAULT_SETTINGS };
let videoComments = [];
// Comments to show after the likes filter, with list-style comments split into one entry per timestamp.
let overlayEntries = [];
let statusTimer = null;
// Marker position (0 to MARKER_BUCKETS - 1) → its comments, most-liked first.
const markerBuckets = new Map();

chrome.storage.sync.get(DEFAULT_SETTINGS, (stored) => {
  settings = stored;
  applySettings();
  rebuildEntries();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync") return;
  for (const [key, { newValue }] of Object.entries(changes)) {
    if (key in DEFAULT_SETTINGS) settings[key] = newValue ?? DEFAULT_SETTINGS[key];
  }
  applySettings();
  if (changes.topPercent) rebuildEntries();
});

const likeFormat = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const formatLikes = (count) => `\u{1F44D} ${likeFormat.format(count ?? 0)}`;

const getPlayer = () => document.getElementById("movie_player");
const getVideo = () => document.querySelector("#movie_player video");
const adShowing = () => getPlayer()?.classList.contains("ad-showing") ?? false;

// null while an ad plays (its duration isn't the video's) or before the video's length is known.
function videoDuration() {
  const duration = getVideo()?.duration;
  return !adShowing() && Number.isFinite(duration) && duration > 0 ? duration : null;
}

// ---------- Splitting list-style comments ----------

// Matches m:ss, mm:ss, mmm:ss, and h:mm:ss, but not pieces of longer runs like 1:2:3:45.
const OVERLAY_TIMESTAMP_PATTERN = /(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?![\d:])/g;

function timestampsIn(text, duration) {
  const found = [];
  for (const match of text.matchAll(OVERLAY_TIMESTAMP_PATTERN)) {
    const [, hours, minutes, seconds] = match;
    if (hours !== undefined && Number(minutes) >= 60) continue;
    const total = Number(hours ?? 0) * 3600 + Number(minutes) * 60 + Number(seconds);
    if (duration !== null && total > duration) continue;
    const lineStart = text.lastIndexOf("\n", match.index - 1) + 1;
    found.push({
      seconds: total,
      start: match.index,
      end: match.index + match[0].length,
      // e.g. "2:15 the drop" or "- 2:15 the drop" on its own line.
      startsLine: /^[\s\-–—•*·>]*$/.test(text.slice(lineStart, match.index)),
    });
  }
  return found;
}

// Strips separators around a piece of text, e.g. " - the drop, " → "the drop".
function cleanSegment(segment) {
  return segment
    .replace(/^[\s\-–—~:|,.;)\]•*·>]+/, "")
    .replace(/[\s\-–—~|,;(\[•*·]+$/, "")
    .replace(/\s+(at|and|then|to)$/i, "")
    .trim();
}

// A comment like "0:00 intro\n2:15 the drop\n5:40 ending" becomes three entries, each shown at its own time
// with only its own text. Ranges ("1:20 - 1:45 the solo") are shown at their start. Ordinary comments that
// happen to mention two times ("the bit from 1:30 to 2:00 is great") stay whole, shown at the first time.
function splitComment(comment, duration) {
  const whole = { ...comment, commentId: comment.id };
  const stamps = timestampsIn(comment.text, duration);
  const isList = stamps.length >= 3 || stamps.filter((s) => s.startsLine).length >= 2;
  if (!isList) return [whole];

  const parts = [];
  let rangeStart = null;
  stamps.forEach((stamp, i) => {
    const text = cleanSegment(comment.text.slice(stamp.end, stamps[i + 1]?.start ?? comment.text.length));
    if (!text) {
      // Nothing between this time and the next, so it's the start of a range (or a bare time at the end).
      rangeStart ??= stamp.seconds;
      return;
    }
    parts.push({ ...whole, id: `${comment.id}#${parts.length}`, timestamp: rangeStart ?? stamp.seconds, text });
    rangeStart = null;
  });
  return parts.length >= 2 ? parts : [whole];
}

function rebuildEntries() {
  const keep = Math.max(1, Math.ceil((videoComments.length * settings.topPercent) / 100));
  const duration = videoDuration();
  overlayEntries = [...videoComments]
    .sort((a, b) => (b.likeCount ?? 0) - (a.likeCount ?? 0))
    .slice(0, keep)
    .flatMap((comment) => splitComment(comment, duration));
  renderMarkers();
  renderOverlay(getVideo()?.currentTime ?? 0);
}

// False for comments that are only timestamps, like "1:30" or "2:15!!". The server stops saving these, but
// older saved copies may still have some.
function hasTextBesidesTimestamps(text) {
  return text.replace(OVERLAY_TIMESTAMP_PATTERN, "").replace(/[\s\p{P}]/gu, "").length > 0;
}

// Only comments with a timestamp and some other text are displayed. Passing [] clears the overlay.
function setOverlayComments(comments) {
  videoComments = comments.filter((c) => typeof c.timestamp === "number" && hasTextBesidesTimestamps(c.text));
  rebuildEntries();
}

// ---------- Overlay ----------

function getOverlay() {
  const player = getPlayer();
  if (!player) return null;
  ensureToggleButton(player);

  let overlay = player.querySelector(".ytc-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "ytc-overlay";
    const status = document.createElement("div");
    status.className = "ytc-status";
    status.hidden = true;
    overlay.append(status);
    player.appendChild(overlay);
    applySettings();
  }
  return overlay;
}

function applySettings() {
  const overlay = getPlayer()?.querySelector(".ytc-overlay");
  if (overlay) {
    const [vertical, horizontal] = settings.position.split("-");
    overlay.dataset.vertical = vertical;
    overlay.dataset.horizontal = horizontal;
    overlay.hidden = !settings.overlayEnabled;
    overlay.style.setProperty("--ytc-font-size", `${settings.fontSize}px`);
    overlay.style.setProperty("--ytc-bg-opacity", settings.backgroundOpacity / 100);
  }
  updateToggleButton();
  renderMarkers();
  renderOverlay(getVideo()?.currentTime ?? 0);
}

function lingerSeconds(entry) {
  return OVERLAY_LINGER_SECONDS + Math.min(OVERLAY_MAX_EXTRA_LINGER_SECONDS, entry.text.length / 40);
}

function openComment(entry) {
  const videoId = new URLSearchParams(location.search).get("v");
  getVideo()?.pause();
  window.open(`https://www.youtube.com/watch?v=${videoId}&lc=${encodeURIComponent(entry.commentId)}`, "_blank", "noopener");
}

function createOverlayItem(entry) {
  const item = document.createElement("div");
  item.className = "ytc-overlay-comment";
  item.dataset.id = entry.id;
  item.title = "Open this comment on YouTube";

  const author = document.createElement("div");
  author.className = "ytc-overlay-author";
  author.textContent = `${entry.author} · ${formatLikes(entry.likeCount)}`;

  const text = document.createElement("div");
  text.className = "ytc-overlay-text";
  text.textContent = entry.text;

  item.append(author, text);
  // Keep clicks from reaching the player, which would pause or play the video.
  for (const type of ["mousedown", "mouseup", "pointerdown", "pointerup", "click", "dblclick"]) {
    item.addEventListener(type, (event) => event.stopPropagation());
  }
  item.addEventListener("click", () => openComment(entry));
  return item;
}

function removeItem(item) {
  item.classList.add("ytc-leaving");
  setTimeout(() => item.remove(), OVERLAY_FADE_MS);
}

function renderOverlay(currentTime) {
  const overlay = getOverlay();
  if (!overlay) return;

  // During ads, currentTime belongs to the ad rather than the video.
  const showing = settings.overlayEnabled && !adShowing();
  const inWindow = (entry) =>
    currentTime >= entry.timestamp - OVERLAY_LEAD_SECONDS && currentTime < entry.timestamp + lingerSeconds(entry);
  const byId = new Map(overlayEntries.map((entry) => [entry.id, entry]));

  // A comment on screen stays until its time is up, even if a more-liked one comes along, so busy stretches
  // don't flicker. One under the mouse stays until the mouse leaves.
  const kept = new Set();
  for (const item of overlay.querySelectorAll(".ytc-overlay-comment:not(.ytc-leaving)")) {
    const entry = byId.get(item.dataset.id);
    if (showing && entry && (inWindow(entry) || item.matches(":hover"))) kept.add(entry.id);
    else removeItem(item);
  }
  if (!showing) return;

  const free = OVERLAY_MAX_VISIBLE - kept.size;
  if (free <= 0) return;
  overlayEntries
    .filter((entry) => !kept.has(entry.id) && inWindow(entry))
    .sort((a, b) => (b.likeCount ?? 0) - (a.likeCount ?? 0))
    .slice(0, free)
    .forEach((entry) => overlay.appendChild(createOverlayItem(entry)));
}

// Shows a short message with the comments, e.g. "Loading comments…". hideAfterMs hides it automatically.
function setOverlayStatus(text, hideAfterMs) {
  const status = getOverlay()?.querySelector(".ytc-status");
  if (!status) return;
  clearTimeout(statusTimer);
  status.textContent = text ?? "";
  status.hidden = !text;
  if (text && hideAfterMs) statusTimer = setTimeout(() => (status.hidden = true), hideAfterMs);
}

// ---------- Progress bar markers ----------

// Bars above the progress bar showing where timestamped comments are; taller means more comments there.
function renderMarkers() {
  const bar = document.querySelector("#movie_player .ytp-progress-bar");
  if (!bar) return;
  let markers = bar.querySelector(".ytc-markers");
  if (!markers) {
    markers = document.createElement("div");
    markers.className = "ytc-markers";
    bar.appendChild(markers);
  }
  markers.replaceChildren();
  markerBuckets.clear();
  hidePreview();

  const duration = videoDuration();
  if (!settings.overlayEnabled || duration === null || overlayEntries.length === 0) return;

  for (const entry of overlayEntries) {
    const bucket = Math.min(MARKER_BUCKETS - 1, Math.floor((entry.timestamp / duration) * MARKER_BUCKETS));
    if (!markerBuckets.has(bucket)) markerBuckets.set(bucket, []);
    markerBuckets.get(bucket).push(entry);
  }
  const most = Math.max(...[...markerBuckets.values()].map((list) => list.length));
  for (const [bucket, list] of markerBuckets) {
    list.sort((a, b) => (b.likeCount ?? 0) - (a.likeCount ?? 0));
    const marker = document.createElement("div");
    marker.className = "ytc-marker";
    marker.dataset.bucket = bucket;
    marker.style.left = `${((bucket + 0.5) / MARKER_BUCKETS) * 100}%`;
    marker.style.height = `${4 + 8 * Math.sqrt(list.length / most)}px`;
    markers.appendChild(marker);
  }
}

// ---------- Marker previews ----------

const PREVIEW_MAX_COMMENTS = 2;
// How close (in pixels) the mouse must be to a marker to preview it.
const PREVIEW_HOVER_DISTANCE_PX = 8;

let previewedBucket = null;

function hidePreview() {
  if (previewedBucket === null) return;
  previewedBucket = null;
  document.querySelector("#movie_player .ytc-marker-preview")?.remove();
  document.querySelector("#movie_player .ytc-marker-active")?.classList.remove("ytc-marker-active");
}

function createPreview(entries) {
  const card = document.createElement("div");
  card.className = "ytc-marker-preview";
  card.style.setProperty("--ytc-bg-opacity", settings.backgroundOpacity / 100);
  for (const entry of entries.slice(0, PREVIEW_MAX_COMMENTS)) {
    const comment = document.createElement("div");
    comment.className = "ytc-marker-preview-comment";
    const author = document.createElement("div");
    author.className = "ytc-overlay-author";
    author.textContent = `${entry.author} · ${formatLikes(entry.likeCount)}`;
    const text = document.createElement("div");
    text.className = "ytc-marker-preview-text";
    text.textContent = entry.text;
    comment.append(author, text);
    card.append(comment);
  }
  const more = entries.length - PREVIEW_MAX_COMMENTS;
  if (more > 0) {
    const footer = document.createElement("div");
    footer.className = "ytc-marker-preview-more";
    footer.textContent = `+${more} more here`;
    card.append(footer);
  }
  return card;
}

// Finds the marker nearest the mouse, if one is close enough.
function bucketNear(clientX, bar) {
  const rect = bar.getBoundingClientRect();
  const bucketWidth = rect.width / MARKER_BUCKETS;
  const center = Math.floor(((clientX - rect.left) / rect.width) * MARKER_BUCKETS);
  let nearest = null;
  let nearestDistance = PREVIEW_HOVER_DISTANCE_PX;
  for (let bucket = center - 3; bucket <= center + 3; bucket++) {
    if (!markerBuckets.has(bucket)) continue;
    const distance = Math.abs(rect.left + (bucket + 0.5) * bucketWidth - clientX);
    if (distance <= nearestDistance) {
      nearest = bucket;
      nearestDistance = distance;
    }
  }
  return nearest;
}

// The top edge of YouTube's thumbnail preview, including hints that stick out above it
// ("Pull up for precise seeking"), or null when it isn't showing.
function tooltipTop(player, barRect) {
  const tooltip = player.querySelector(".ytp-tooltip");
  if (!tooltip || getComputedStyle(tooltip).display === "none") return null;
  let top = null;
  for (const element of [tooltip, ...tooltip.querySelectorAll("*")]) {
    const rect = element.getBoundingClientRect();
    if (rect.height > 0 && rect.top < barRect.top && (top === null || rect.top < top)) top = rect.top;
  }
  return top;
}

function showPreview(bucket, bar) {
  const player = getPlayer();
  if (!player) return;
  if (bucket !== previewedBucket) {
    hidePreview();
    previewedBucket = bucket;
    player.querySelector(`.ytc-marker[data-bucket="${bucket}"]`)?.classList.add("ytc-marker-active");
    player.appendChild(createPreview(markerBuckets.get(bucket)));
  }

  // Sits above YouTube's thumbnail preview when that's showing, otherwise just above the progress bar.
  const card = player.querySelector(".ytc-marker-preview");
  const playerRect = player.getBoundingClientRect();
  const barRect = bar.getBoundingClientRect();
  const above = Math.min(barRect.top - 14, tooltipTop(player, barRect) ?? Infinity);
  card.style.bottom = `${playerRect.bottom - above + 8}px`;

  const markerX = barRect.left + ((bucket + 0.5) / MARKER_BUCKETS) * barRect.width - playerRect.left;
  const half = card.offsetWidth / 2;
  card.style.left = `${Math.min(Math.max(markerX, half + 12), playerRect.width - half - 12)}px`;
}

document.addEventListener(
  "mousemove",
  (event) => {
    if (markerBuckets.size === 0 || !settings.overlayEnabled) return hidePreview();
    const bar = event.target.closest?.("#movie_player .ytp-progress-bar-container")?.querySelector(".ytp-progress-bar");
    const bucket = bar ? bucketNear(event.clientX, bar) : null;
    if (bucket === null) hidePreview();
    else showPreview(bucket, bar);
  },
  true
);

// ---------- On/off button and shortcut ----------

function svgElement(tag, attributes) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

function ensureToggleButton(player) {
  if (player.querySelector(".ytc-toggle-button")) return;
  const controls = player.querySelector(".ytp-right-controls");
  if (!controls) return;

  const button = document.createElement("button");
  button.className = "ytp-button ytc-toggle-button";
  // A speech bubble, with a slash drawn over it when the overlay is off.
  const svg = svgElement("svg", { viewBox: "0 0 24 24", width: "100%", height: "100%" });
  svg.append(
    svgElement("path", {
      d: "M5 6.5A1.5 1.5 0 0 1 6.5 5h11A1.5 1.5 0 0 1 19 6.5v7a1.5 1.5 0 0 1-1.5 1.5H11l-3.5 3v-3h-1A1.5 1.5 0 0 1 5 13.5z",
      fill: "none",
      stroke: "#fff",
      "stroke-width": "1.6",
      "stroke-linejoin": "round",
    }),
    svgElement("path", { class: "ytc-toggle-dots", d: "M9 10h.01M12 10h.01M15 10h.01", stroke: "#fff", "stroke-width": "2", "stroke-linecap": "round" }),
    svgElement("path", { class: "ytc-toggle-slash", d: "M4 4l16 16", stroke: "#fff", "stroke-width": "1.6", "stroke-linecap": "round" })
  );
  button.append(svg);
  for (const type of ["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick"]) {
    button.addEventListener(type, (event) => event.stopPropagation());
  }
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleOverlay();
  });
  controls.prepend(button);
  updateToggleButton();
}

function updateToggleButton() {
  const button = document.querySelector("#movie_player .ytc-toggle-button");
  if (!button) return;
  const label = `${settings.overlayEnabled ? "Hide" : "Show"} timestamped comments (${TOGGLE_SHORTCUT_KEY})`;
  button.setAttribute("aria-pressed", String(settings.overlayEnabled));
  button.setAttribute("aria-label", label);
  button.title = label;
}

function toggleOverlay() {
  settings.overlayEnabled = !settings.overlayEnabled;
  applySettings();
  chrome.storage.sync.set({ overlayEnabled: settings.overlayEnabled });
}

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key.toLowerCase() !== TOGGLE_SHORTCUT_KEY || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.composedPath()[0];
    if (target?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName)) return;
    if (location.pathname !== "/watch" || !getPlayer()) return;
    toggleOverlay();
  },
  true
);

// ---------- Player events ----------

// Media events don't bubble, so listen in the capture phase. This also survives YouTube swapping out the <video> element.
// "seeking" updates the overlay as soon as the user jumps, before the new position finishes buffering.
for (const type of ["timeupdate", "seeking"]) {
  document.addEventListener(
    type,
    (event) => {
      if (event.target.closest?.("#movie_player")) renderOverlay(event.target.currentTime);
    },
    true
  );
}

// The video's length (needed for markers and splitting) changes when it loads and around ads.
document.addEventListener(
  "durationchange",
  (event) => {
    if (event.target.closest?.("#movie_player")) rebuildEntries();
  },
  true
);
