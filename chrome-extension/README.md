Folder containing the chrome extension.

## Install (unpacked, for development)

1. Open Chrome and go to `chrome://extensions`.
2. Enable **Developer mode** (toggle in the top right).
3. Click **Load unpacked**.
4. Select this `chrome-extension` folder.
5. The extension icon will appear in the toolbar. Click it to see the popup.

After editing files, click the refresh icon on the extension's card in `chrome://extensions`, then reload any open YouTube tab to pick up content script changes.

## What's included

- `popup.html` — toolbar popup ("Hello World").
- `content.js` / `content.css` — injects a "Hello World" bubble next to the video timestamp on `youtube.com` watch pages.
