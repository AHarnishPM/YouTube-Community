const preview = document.getElementById("preview");
const positionButtons = document.querySelectorAll("#position-picker button");

// Each slider: its settings key and how to show its value.
const sliders = {
  topPercent: { id: "top-percent", format: (v) => (v >= 100 ? "All" : `Top ${v}% by likes`) },
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
  for (const button of positionButtons) {
    const selected = button.dataset.position === position;
    button.setAttribute("aria-pressed", String(selected));
    if (selected) document.getElementById("position-value").textContent = button.getAttribute("aria-label");
  }
}

chrome.storage.sync.get(DEFAULT_SETTINGS, (settings) => {
  for (const key of Object.keys(sliders)) showSlider(key, settings[key]);
  showPosition(settings.position);
  document.getElementById("overlay-enabled").checked = settings.overlayEnabled;
});

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
enabledBox.addEventListener("change", () => chrome.storage.sync.set({ overlayEnabled: enabledBox.checked }));

// The player button and keyboard shortcut can change this while the popup is open.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.overlayEnabled) enabledBox.checked = changes.overlayEnabled.newValue;
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
