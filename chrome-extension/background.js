importScripts("config.js");

const REFRESH_TOKEN_KEY = "firebaseRefreshToken";
const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;

let cachedToken = null;

async function signInAnonymously() {
  const res = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${FIREBASE_CONFIG.apiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ returnSecureToken: true }),
    }
  );
  if (!res.ok) throw new Error(`anonymous sign-in failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  return { idToken: data.idToken, refreshToken: data.refreshToken, expiresIn: Number(data.expiresIn) };
}

async function refreshSession(refreshToken) {
  const res = await fetch(`https://securetoken.googleapis.com/v1/token?key=${FIREBASE_CONFIG.apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return { idToken: data.id_token, refreshToken: data.refresh_token, expiresIn: Number(data.expires_in) };
}

// Reuses one anonymous Firebase user across sessions instead of creating a new user per sign-in.
async function getIdToken() {
  if (cachedToken && Date.now() < cachedToken.expiresAt) return cachedToken.idToken;

  const { [REFRESH_TOKEN_KEY]: storedRefreshToken } = await chrome.storage.local.get(REFRESH_TOKEN_KEY);
  const session = (storedRefreshToken && (await refreshSession(storedRefreshToken))) || (await signInAnonymously());

  await chrome.storage.local.set({ [REFRESH_TOKEN_KEY]: session.refreshToken });
  cachedToken = { idToken: session.idToken, expiresAt: Date.now() + (session.expiresIn - 60) * 1000 };
  return cachedToken.idToken;
}

async function saveTranscript({ videoId, ...transcript }) {
  if (!VIDEO_ID_PATTERN.test(videoId)) throw new Error(`invalid video id: ${videoId}`);

  const idToken = await getIdToken();
  const url = `${FIREBASE_CONFIG.databaseURL}/videos/${videoId}/transcript.json?auth=${encodeURIComponent(idToken)}`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...transcript, fetchedAt: Date.now() }),
  });
  if (!res.ok) throw new Error(`database write failed: ${res.status} ${await res.text()}`);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "saveTranscript") return;
  saveTranscript(message.transcript).then(
    () => sendResponse({ ok: true }),
    (err) => sendResponse({ ok: false, error: err.message })
  );
  return true;
});
