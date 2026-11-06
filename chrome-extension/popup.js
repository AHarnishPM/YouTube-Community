const slider = document.getElementById("font-size");
const valueLabel = document.getElementById("font-size-value");
const preview = document.getElementById("preview");

function showFontSize(size) {
  slider.value = size;
  valueLabel.textContent = `${size}px`;
  preview.style.fontSize = `${size}px`;
}

chrome.storage.sync.get({ fontSize: 16 }, ({ fontSize }) => showFontSize(fontSize));

slider.addEventListener("input", () => showFontSize(Number(slider.value)));

// Saved on release, not on every drag step, to stay under chrome.storage.sync's write rate limit.
slider.addEventListener("change", () => chrome.storage.sync.set({ fontSize: Number(slider.value) }));
