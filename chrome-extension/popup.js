const preview = document.getElementById("preview");
const positionButtons = document.querySelectorAll("#position-picker button");

// Each slider: its settings key and how to show its value.
const sliders = {
  fontSize: { id: "font-size", format: (v) => `${v}px` },
  backgroundOpacity: { id: "background-opacity", format: (v) => `${v}%` },
};

function showPreview(key, value) {
  if (key === "fontSize") preview.style.fontSize = `${value}px`;
  if (key === "backgroundOpacity") preview.style.backgroundColor = `rgba(0, 0, 0, ${value / 100})`;
}

function showSlider(key, value) {
  const { id, format } = sliders[key];
  document.getElementById(id).value = value;
  document.getElementById(`${id}-value`).textContent = format(value);
  showPreview(key, value);
}

function showPosition(position) {
  // "custom" (set by dragging on the video) matches none of the buttons.
  let label = "Custom";
  for (const button of positionButtons) {
    const selected = button.dataset.position === position;
    button.setAttribute("aria-pressed", String(selected));
    if (selected) label = button.getAttribute("aria-label");
  }
  document.getElementById("position-value").textContent = label;
}

chrome.storage.sync.get(DEFAULT_SETTINGS, (settings) => {
  for (const key of Object.keys(sliders)) showSlider(key, settings[key]);
  showPosition(settings.position);
  showTiming(-settings.leadSeconds, settings.lingerSeconds);
  document.getElementById("overlay-enabled").checked = settings.overlayEnabled;
  zeroLikesBox.checked = settings.showZeroLikes;
});

// ---------- On-screen timing: one track, two dots ----------
// Values are seconds relative to the timestamp: the left dot is when comments appear (negative = before),
// the right dot is when they disappear.

const timingStart = document.getElementById("timing-start");
const timingEnd = document.getElementById("timing-end");
const TIMING_MIN = Number(timingStart.min);
const TIMING_MAX = Number(timingStart.max);
const TIMING_GAP = 0.5;

const percentAlong = (value) => ((value - TIMING_MIN) / (TIMING_MAX - TIMING_MIN)) * 100;

function describeOffset(seconds) {
  if (seconds === 0) return "at the timestamp";
  return `${Math.abs(seconds)}s ${seconds < 0 ? "before" : "after"}`;
}

function showTiming(start, end) {
  timingStart.value = start;
  timingEnd.value = end;
  const fill = document.getElementById("timing-fill");
  fill.style.left = `${percentAlong(start)}%`;
  fill.style.width = `${percentAlong(end) - percentAlong(start)}%`;
  document.getElementById("timing-zero").style.left = `${percentAlong(0)}%`;
  // The label sits under the timestamp mark (the rail is inset 8px from each side).
  document.getElementById("timing-zero-label").style.left = `calc(8px + (100% - 16px) * ${percentAlong(0) / 100})`;
  document.getElementById("timing-value").textContent = `${describeOffset(start)} → ${describeOffset(end)}`;
}

// The dots can't cross: each stops just short of the other.
timingStart.addEventListener("input", () => {
  showTiming(Math.min(Number(timingStart.value), Number(timingEnd.value) - TIMING_GAP), Number(timingEnd.value));
});
timingEnd.addEventListener("input", () => {
  showTiming(Number(timingStart.value), Math.max(Number(timingEnd.value), Number(timingStart.value) + TIMING_GAP));
});
for (const input of [timingStart, timingEnd]) {
  input.addEventListener("change", () =>
    chrome.storage.sync.set({ leadSeconds: -Number(timingStart.value), lingerSeconds: Number(timingEnd.value) })
  );
}

for (const [key, { id }] of Object.entries(sliders)) {
  const slider = document.getElementById(id);
  slider.addEventListener("input", () => showSlider(key, Number(slider.value)));
  // Saved on release, not on every drag step, to stay under chrome.storage.sync's write rate limit.
  slider.addEventListener("change", () => chrome.storage.sync.set({ [key]: Number(slider.value) }));
}

for (const button of positionButtons) {
  button.addEventListener("click", () => {
    showPosition(button.dataset.position);
    chrome.storage.sync.set({ position: button.dataset.position });
  });
}

const enabledBox = document.getElementById("overlay-enabled");
const zeroLikesBox = document.getElementById("show-zero-likes");
zeroLikesBox.addEventListener("change", () => chrome.storage.sync.set({ showZeroLikes: zeroLikesBox.checked }));
enabledBox.addEventListener("change", () => chrome.storage.sync.set({ overlayEnabled: enabledBox.checked }));

// The player button and keyboard shortcut can change this while the popup is open.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync") return;
  if (changes.overlayEnabled) enabledBox.checked = changes.overlayEnabled.newValue;
  if (changes.position) showPosition(changes.position.newValue);
});

document.getElementById("privacy-link").href = `${WORKER_URL}/privacy`;

async function showConsent() {
  const consented = await hasConsent();
  document.getElementById("consent-needed").hidden = consented;
  document.getElementById("turn-off-row").hidden = !consented;
}
showConsent();

document.getElementById("review").addEventListener("click", () => chrome.tabs.create({ url: "welcome.html" }));
document.getElementById("turn-off").addEventListener("click", async () => {
  await withdrawConsent();
  showConsent();
});
