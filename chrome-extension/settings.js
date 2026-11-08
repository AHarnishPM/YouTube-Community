// User settings, saved in chrome.storage.sync. Shared by the popup and the YouTube content scripts.
const DEFAULT_SETTINGS = {
  overlayEnabled: true,
  // "top" or "bottom", then "left", "center", or "right".
  position: "top-center",
  fontSize: 16,
  // Percent of the background's darkness, 20–100.
  backgroundOpacity: 60,
  // Percent of a video's timestamped comments to show, ranked by likes (100 = all).
  topPercent: 100,
};

const TOGGLE_SHORTCUT_KEY = "b";
