const OVERLAY_LEAD_SECONDS = 5;
const OVERLAY_LINGER_SECONDS = 5;
const OVERLAY_MAX_VISIBLE = 3;
const OVERLAY_DEFAULT_FONT_SIZE = 16;
const OVERLAY_FADE_MS = 300;

let overlayComments = [];

function getOverlay() {
  const player = document.getElementById("movie_player");
  if (!player) return null;

  let overlay = player.querySelector(".ytc-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "ytc-overlay";
    player.appendChild(overlay);
    chrome.storage.sync.get({ fontSize: OVERLAY_DEFAULT_FONT_SIZE }, ({ fontSize }) => {
      overlay.style.setProperty("--ytc-font-size", `${fontSize}px`);
    });
  }
  return overlay;
}

function createOverlayItem(comment) {
  const item = document.createElement("div");
  item.className = "ytc-overlay-comment";
  item.dataset.id = comment.id;

  const author = document.createElement("div");
  author.className = "ytc-overlay-author";
  author.textContent = comment.author;

  const text = document.createElement("div");
  text.className = "ytc-overlay-text";
  text.textContent = comment.text;

  item.append(author, text);
  return item;
}

function renderOverlay(currentTime) {
  const overlay = getOverlay();
  if (!overlay) return;

  // During ads, currentTime belongs to the ad rather than the video.
  const adShowing = overlay.parentElement.classList.contains("ad-showing");
  const active = adShowing
    ? []
    : overlayComments
        .filter((c) => currentTime >= c.timestamp - OVERLAY_LEAD_SECONDS && currentTime < c.timestamp + OVERLAY_LINGER_SECONDS)
        .sort((a, b) => b.likeCount - a.likeCount)
        .slice(0, OVERLAY_MAX_VISIBLE);
  const activeIds = new Set(active.map((c) => c.id));

  // Existing items are left in place rather than re-rendered so they don't flash or reorder.
  const shownIds = new Set();
  for (const item of overlay.querySelectorAll(".ytc-overlay-comment:not(.ytc-leaving)")) {
    if (activeIds.has(item.dataset.id)) {
      shownIds.add(item.dataset.id);
    } else {
      item.classList.add("ytc-leaving");
      setTimeout(() => item.remove(), OVERLAY_FADE_MS);
    }
  }
  for (const comment of active) {
    if (!shownIds.has(comment.id)) overlay.appendChild(createOverlayItem(comment));
  }
}

// Only comments with a timestamp are displayed. Passing [] clears the overlay.
function setOverlayComments(comments) {
  overlayComments = comments.filter((c) => typeof c.timestamp === "number");
  const video = document.querySelector("#movie_player video");
  renderOverlay(video ? video.currentTime : 0);
}

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

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync" || !changes.fontSize) return;
  document.querySelector(".ytc-overlay")?.style.setProperty("--ytc-font-size", `${changes.fontSize.newValue}px`);
});
