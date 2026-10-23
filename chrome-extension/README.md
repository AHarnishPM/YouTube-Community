Folder containing the chrome extension.

## Firebase setup (one time)

Transcripts are saved to a Firebase Realtime Database at `videos/{videoId}/transcript`. Put your own data under the same video as a sibling key (e.g. `videos/{videoId}/notes`); the extension only ever overwrites `transcript`.

1. In the [Firebase console](https://console.firebase.google.com), open your project.
2. **Build → Realtime Database → Create Database**. Pick a location and start in **locked mode**.
3. On the database's **Rules** tab, paste the contents of `database.rules.json` and click **Publish**.
4. **Build → Authentication → Get started → Sign-in method**, then enable **Anonymous**.
5. **Project settings** (gear icon) **→ General → Your apps**. If there's no web app, add one (the `</>` icon). Copy its `apiKey`.
6. Copy `config.example.js` to `config.js` and fill in the `apiKey` and the database URL (shown at the top of the Realtime Database **Data** tab).

`config.js` is gitignored. The extension won't load until it exists.

## Install (unpacked, for development)

1. Open Chrome and go to `chrome://extensions`.
2. Enable **Developer mode** (toggle in the top right).
3. Click **Load unpacked**.
4. Select this `chrome-extension` folder.
5. The extension icon will appear in the toolbar. Click it to see the popup.

After editing files, click the refresh icon on the extension's card in `chrome://extensions`, then reload any open YouTube tab to pick up content script changes.

## What's included

- `popup.html` — toolbar popup ("Hello World").
- `content.js` / `content.css` — injects a "Hello World" bubble next to the video timestamp on `youtube.com` watch pages, and logs the first 100 transcript lines to the page's DevTools console.
- `transcript.js` — `fetchTranscript(videoId)` pulls the full caption track from YouTube's internal player API (same approach as the Python `youtube-transcript-api`).
- `background.js` — signs in to Firebase anonymously and writes each transcript to the database.
- `database.rules.json` — security rules: signed-in users only, keys must be valid 11-character video IDs.
