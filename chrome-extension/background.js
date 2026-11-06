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

// Matches m:ss, mm:ss, mmm:ss, and h:mm:ss, but not pieces of longer runs like 1:2:3:45.
const TIMESTAMP_PATTERN = /(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?![\d:])/g;

// Out-of-range matches are skipped since they're probably not timestamps (e.g. "9:45 am").
function firstTimestampSeconds(text, durationSeconds) {
  for (const [, hours, minutes, seconds] of text.matchAll(TIMESTAMP_PATTERN)) {
    if (hours !== undefined && Number(minutes) >= 60) continue;
    const total = Number(hours ?? 0) * 3600 + Number(minutes) * 60 + Number(seconds);
    if (durationSeconds === null || total <= durationSeconds) return total;
  }
  return null;
}

// One page is up to 100 top-level comments, newest first, and costs 1 unit of YouTube API quota.
// Only comments published at or after sinceMs (if given) are considered; reachedSince tells the
// caller that older comments started appearing, so there's no need to fetch further pages.
async function fetchTimestampedCommentsPage(videoId, durationSeconds, pageToken, sinceMs) {
  if (typeof YOUTUBE_API_KEY === "undefined") {
    throw new Error(
      "YOUTUBE_API_KEY is missing from config.js. Declare it as its own `const YOUTUBE_API_KEY = \"...\";`, not inside FIREBASE_CONFIG."
    );
  }

  const params = new URLSearchParams({
    part: "snippet",
    videoId,
    maxResults: "100",
    order: "time",
    textFormat: "plainText",
    key: YOUTUBE_API_KEY,
  });
  if (pageToken) params.set("pageToken", pageToken);
  const res = await fetch(`https://www.googleapis.com/youtube/v3/commentThreads?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(`comments request failed: ${res.status} ${body?.error?.message ?? ""}`);
  }
  const data = await res.json();

  const newItems = sinceMs
    ? data.items.filter((item) => Date.parse(item.snippet.topLevelComment.snippet.publishedAt) >= sinceMs)
    : data.items;

  const comments = newItems
    .map((item) => {
      const comment = item.snippet.topLevelComment.snippet;
      return {
        id: item.id,
        author: comment.authorDisplayName,
        text: comment.textDisplay,
        timestamp: firstTimestampSeconds(comment.textDisplay, durationSeconds),
        likeCount: comment.likeCount,
        replyCount: item.snippet.totalReplyCount,
        publishedAt: comment.publishedAt,
      };
    })
    .filter((c) => c.timestamp !== null);

  return {
    comments,
    scanned: newItems.length,
    reachedSince: newItems.length < data.items.length,
    nextPageToken: data.nextPageToken ?? null,
  };
}

async function getStoredComments({ videoId }) {
  if (!VIDEO_ID_PATTERN.test(videoId)) throw new Error(`invalid video id: ${videoId}`);
  const idToken = await getIdToken();
  const res = await fetch(
    `${FIREBASE_CONFIG.databaseURL}/videos/${videoId}/comments.json?auth=${encodeURIComponent(idToken)}`
  );
  if (!res.ok) throw new Error(`database read failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// PATCH only replaces the listed children, so other data under the video (e.g. communityNotes) is untouched.
async function updateVideo(videoId, fields) {
  const idToken = await getIdToken();
  const url = `${FIREBASE_CONFIG.databaseURL}/videos/${videoId}.json?auth=${encodeURIComponent(idToken)}`;
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) throw new Error(`database write failed: ${res.status} ${await res.text()}`);
}

// Fields left undefined (because fetching them failed) are not written, so previously saved copies are kept.
async function saveVideo({ videoId, transcript, chapters, comments }) {
  if (!VIDEO_ID_PATTERN.test(videoId)) throw new Error(`invalid video id: ${videoId}`);

  const fields = {};
  if (transcript) fields.transcript = { ...transcript, fetchedAt: Date.now() };
  // A "chapters/creator" path key updates only that child, leaving chapters/generated alone.
  // Writing null deletes stale chapters if the creator has since removed them.
  if (chapters) {
    fields["chapters/creator"] = chapters.length > 0 ? { fetchedAt: Date.now(), items: chapters } : null;
  }
  if (comments) fields.comments = comments;

  if (Object.keys(fields).length > 0) await updateVideo(videoId, fields);
}

const messageHandlers = {
  fetchCommentsPage: ({ videoId, durationSeconds, pageToken, sinceMs }) =>
    fetchTimestampedCommentsPage(videoId, durationSeconds, pageToken, sinceMs),
  getStoredComments,
  saveVideo,
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = messageHandlers[message.type];
  if (!handler) return;
  handler(message).then(
    (value) => sendResponse({ ok: true, value }),
    (err) => sendResponse({ ok: false, error: err.message })
  );
  return true;
});
