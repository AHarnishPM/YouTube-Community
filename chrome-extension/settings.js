// User settings, saved in chrome.storage.sync. Shared by the popup and the YouTube content scripts.
const DEFAULT_SETTINGS = {
  overlayEnabled: true,
  // "top" or "bottom", then "left", "center", or "right"; or "custom" after dragging the comments.
  position: "top-center",
  // With position "custom": the comments' center and top edge, as fractions of the player's width and height.
  customX: 0.5,
  customY: 0.05,
  // Comments appear this many seconds before their timestamp and stay until this many seconds after.
  leadSeconds: 2.5,
  lingerSeconds: 5.5,
  fontSize: 16,
  // Percent of the background's darkness, 20–100.
  backgroundOpacity: 60,
  // Percent of a video's timestamped comments to show, ranked by likes (100 = all).
  topPercent: 100,
};

const TOGGLE_SHORTCUT_KEY = "b";
