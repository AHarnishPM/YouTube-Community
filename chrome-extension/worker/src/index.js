// Server side of the extension. It holds the YouTube API key and Firebase service account, so neither ships
// in the extension, and it's the only thing that can read or write the database.
import privacyPolicy from "./privacy.html";

const VIDEO_PATH = /^\/videos\/([A-Za-z0-9_-]{11})(\/content|\/notes)?$/;

const COMMENTS_REFRESH_MS = 3 * 60 * 60 * 1000;
// A full rescan re-reads every comment, picking up new like counts and dropping deleted comments. Between
// full rescans, refreshes only add newly posted comments. YouTube's API policies also require stored API data
// to be refreshed or deleted within 30 days (see deleteExpiredData).
const FULL_RESCAN_MS = 3 * 24 * 60 * 60 * 1000;
const RETENTION_MS = 29 * 24 * 60 * 60 * 1000;
// Overlap the previous refresh slightly in case clocks disagree.
const CLOCK_SKEW_MS = 60 * 1000;

// Free Workers allow 50 outgoing requests per call, so long scans continue over several calls from the extension.
const PAGES_PER_CALL = 10;
const MAX_SCAN_PAGES = 100;
const ABANDONED_SCAN_MS = 10 * 60 * 1000;
// Stops refreshing (but keeps serving saved data) before the 10,000-unit daily YouTube quota runs out.
const DAILY_UNIT_BUDGET = 8000;

// Where each kind of expiring data lives under videos/{videoId}.
const EXPIRING_PATHS = {
  comments: ["comments"],
  commentScan: ["commentScan"],
  transcript: ["transcript"],
  chapters: ["chapters/creator", "chapters/auto"],
};

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/privacy") {
      return new Response(privacyPolicy, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    try {
      const match = url.pathname.match(VIDEO_PATH);
      if (!match) throw new HttpError(404, "not found");
      const [, videoId, action] = match;
      const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
      if (!(await allowed(env.REQUEST_LIMITER, ip))) throw new HttpError(429, "too many requests, try again in a minute");

      if (!action && request.method === "GET") return json(await getVideo(env, videoId, ip));
      if (action === "/content" && request.method === "POST") return json(await saveContent(env, videoId, request));
      if (action === "/notes" && request.method === "POST") return json(await addNotes(env, videoId, request));
      throw new HttpError(405, "method not allowed");
    } catch (err) {
      if (err instanceof HttpError) return json({ error: err.message }, err.status);
      console.error(err);
      return json({ error: "server error" }, 500);
    }
  },

  async scheduled(_event, env) {
    await deleteExpiredData(env);
  },
};

async function allowed(limiter, key) {
  if (!limiter) {
    console.warn("rate limiter binding is missing; check wrangler.toml");
    return true;
  }
  return (await limiter.limit({ key })).success;
}

// ---------- Firebase ----------

let cachedAccessToken = null;

function base64url(data) {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Signs in as the service account, which has full database access regardless of the security rules.
async function getAccessToken(env) {
  if (cachedAccessToken && Date.now() < cachedAccessToken.expiresAt) return cachedAccessToken.token;

  const account = JSON.parse(env.FIREBASE_SERVICE_ACCOUNT);
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = base64url(
    JSON.stringify({
      iss: account.client_email,
      scope: "https://www.googleapis.com/auth/firebase.database https://www.googleapis.com/auth/userinfo.email",
      aud: "https://oauth2.googleapis.com/token",
      iat: now,
      exp: now + 3600,
    })
  );
  const pem = account.private_key.replace(/-----[^-]+-----|\s/g, "");
  const key = await crypto.subtle.importKey(
    "pkcs8",
    Uint8Array.from(atob(pem), (c) => c.charCodeAt(0)),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${header}.${claims}`));

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${header}.${claims}.${base64url(signature)}`,
    }),
  });
  if (!res.ok) throw new Error(`service account sign-in failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  cachedAccessToken = { token: data.access_token, expiresAt: Date.now() + (data.expires_in - 60) * 1000 };
  return cachedAccessToken.token;
}

async function db(env, method, path, { body, query } = {}) {
  const url = new URL(`${env.FIREBASE_DATABASE_URL.replace(/\/$/, "")}/${path}.json`);
  for (const [name, value] of Object.entries(query ?? {})) url.searchParams.set(name, value);
  const res = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${await getAccessToken(env)}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`database ${method} /${path} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// A root-level PATCH writes every listed path in one atomic update; null deletes a path.
const updatePaths = (env, updates) => db(env, "PATCH", "", { body: updates });

// ---------- YouTube Data API ----------

function quotaDay() {
  // YouTube's quota resets at midnight Pacific time.
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date());
}

async function youtube(env, resource, params) {
  const query = new URLSearchParams({ ...params, key: env.YOUTUBE_API_KEY });
  const res = await fetch(`https://www.googleapis.com/youtube/v3/${resource}?${query}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(`YouTube ${resource} request failed: ${res.status} ${data?.error?.message ?? ""}`);
    err.reason = data?.error?.errors?.[0]?.reason;
    throw err;
  }
  return data;
}

// Resolves to undefined if the video doesn't exist, or null if it has no fixed length (live streams).
async function fetchDuration(env, videoId) {
  const data = await youtube(env, "videos", { part: "contentDetails", id: videoId, fields: "items(contentDetails/duration)" });
  const iso = data.items?.[0]?.contentDetails?.duration;
  if (iso === undefined) return undefined;
  const [, days, hours, minutes, seconds] = iso.match(/^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/) ?? [];
  const total = Number(days ?? 0) * 86400 + Number(hours ?? 0) * 3600 + Number(minutes ?? 0) * 60 + Number(seconds ?? 0);
  return total || null;
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

// One page is up to 100 top-level comments, newest first, and costs 1 quota unit. Only comments published at
// or after sinceMs (if set) count; reachedSince means older ones started appearing, so the scan can stop.
async function fetchCommentsPage(env, videoId, durationSeconds, pageToken, sinceMs) {
  const params = {
    part: "snippet",
    videoId,
    maxResults: "100",
    order: "time",
    textFormat: "plainText",
    fields: "nextPageToken,items(id,snippet(totalReplyCount,topLevelComment/snippet(authorDisplayName,textDisplay,likeCount,publishedAt)))",
  };
  if (pageToken) params.pageToken = pageToken;
  const data = await youtube(env, "commentThreads", params);
  const items = data.items ?? [];

  const newItems = sinceMs
    ? items.filter((item) => Date.parse(item.snippet.topLevelComment.snippet.publishedAt) >= sinceMs)
    : items;
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

  return { comments, scanned: newItems.length, reachedSince: newItems.length < items.length, nextPageToken: data.nextPageToken ?? null };
}

// ---------- GET /videos/{id} ----------

// Firebase returns a stored list as an object instead of an array when it has gaps, so accept either.
const asList = (value) => (Array.isArray(value) ? value : Object.values(value ?? {}));
const mergeById = (...lists) => [...new Map(lists.flatMap(asList).map((c) => [c.id, c])).values()];

// Returns the saved timestamped comments, refreshing them first if they're over 3 hours old.
// scanning: true means the scan isn't finished and the extension should call again for more.
async function getVideo(env, videoId, ip) {
  const [storedComments, storedScan, expiry] = await Promise.all([
    db(env, "GET", `videos/${videoId}/comments`),
    db(env, "GET", `videos/${videoId}/commentScan`),
    db(env, "GET", `expiry/${videoId}`),
  ]);
  // Comments saved before the Worker existed have no fullScanAt; rescan them.
  const stored = storedComments?.fullScanAt === undefined ? null : storedComments;
  const now = Date.now();
  const view = (scan) => ({
    comments: mergeById(stored?.items, scan?.items),
    scanning: Boolean(scan),
    transcriptFetchedAt: expiry?.transcript ?? null,
    chaptersFetchedAt: expiry?.chapters ?? null,
  });

  let scan = storedScan && now - storedScan.updatedAt < ABANDONED_SCAN_MS ? storedScan : null;
  if (!scan) {
    if (stored && now - stored.fetchedAt < COMMENTS_REFRESH_MS) return view(null);
    const full = !stored || now - stored.fullScanAt > FULL_RESCAN_MS;
    // Full scans are the expensive kind (up to 100 quota units), so they get their own tighter limit.
    if (full && !(await allowed(env.SCAN_LIMITER, ip))) return view(null);
    if (!(await hasQuota(env))) return view(null);

    const durationSeconds = full || stored.durationSeconds === undefined ? await fetchDuration(env, videoId) : stored.durationSeconds;
    if (durationSeconds === undefined) throw new HttpError(404, "video not found");
    await spendQuota(env, 1);
    scan = { startedAt: now, full, sinceMs: full ? 0 : stored.fetchedAt - CLOCK_SKEW_MS, durationSeconds, pages: 0, scanned: 0, items: [] };
  } else if (!(await hasQuota(env))) {
    return view(null);
  }

  let done = false;
  let pagesThisCall = 0;
  try {
    while (!done && pagesThisCall < PAGES_PER_CALL) {
      const page = await fetchCommentsPage(env, videoId, scan.durationSeconds ?? null, scan.pageToken, scan.sinceMs || null);
      pagesThisCall++;
      scan.items = mergeById(scan.items, page.comments);
      scan.scanned += page.scanned;
      scan.pages++;
      scan.pageToken = page.nextPageToken;
      done = !page.nextPageToken || page.reachedSince || scan.pages >= MAX_SCAN_PAGES;
    }
  } catch (err) {
    if (err.reason !== "commentsDisabled") throw err;
    scan.items = [];
    done = true;
  } finally {
    if (pagesThisCall > 0) await spendQuota(env, pagesThisCall);
  }

  if (!done) {
    await updatePaths(env, {
      [`videos/${videoId}/commentScan`]: { ...scan, updatedAt: Date.now() },
      [`expiry/${videoId}/commentScan`]: scan.startedAt,
    });
    return view(scan);
  }

  const fullScanAt = scan.full ? scan.startedAt : stored.fullScanAt;
  const saved = {
    fetchedAt: scan.startedAt,
    fullScanAt,
    durationSeconds: scan.durationSeconds ?? null,
    scannedCount: scan.full ? scan.scanned : stored.scannedCount + scan.scanned,
    items: scan.full ? scan.items : mergeById(stored.items, scan.items),
  };
  await updatePaths(env, {
    [`videos/${videoId}/comments`]: saved,
    [`videos/${videoId}/commentScan`]: null,
    [`expiry/${videoId}/comments`]: fullScanAt,
    [`expiry/${videoId}/commentScan`]: null,
  });
  return { ...view(null), comments: saved.items };
}

async function hasQuota(env) {
  const used = (await db(env, "GET", `quota/${quotaDay()}`)) ?? 0;
  return used + PAGES_PER_CALL + 1 <= DAILY_UNIT_BUDGET;
}

const spendQuota = (env, units) => updatePaths(env, { [`quota/${quotaDay()}`]: { ".sv": { increment: units } } });

// ---------- POST /videos/{id}/content ----------

const MAX_BODY_CHARS = 4_000_000;

function readNumber(value, { positive = false } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || (positive && value === 0)) {
    throw new HttpError(400, "invalid number");
  }
  return value;
}

function readString(value, maxLength, { optional = false } = {}) {
  if (optional && value === undefined) return undefined;
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) throw new HttpError(400, "invalid text");
  return value;
}

function readArray(value, maxLength) {
  if (!Array.isArray(value) || value.length > maxLength) throw new HttpError(400, "invalid list");
  return value;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_BODY_CHARS) throw new HttpError(413, "request too large");
  try {
    return JSON.parse(text);
  } catch {
    throw new HttpError(400, "invalid JSON");
  }
}

// Rebuilds the data from known fields only, so nothing unexpected can be written to the database.
function cleanTranscript(transcript) {
  if (transcript === null) return null;
  if (typeof transcript?.autoGenerated !== "boolean") throw new HttpError(400, "invalid transcript");
  return {
    languageCode: readString(transcript.languageCode, 35),
    autoGenerated: transcript.autoGenerated,
    lines: readArray(transcript.lines, 50000).map((line) => ({
      start: readNumber(line?.start),
      duration: readNumber(line?.duration),
      text: readString(line?.text, 2000),
    })),
  };
}

function cleanChapters(list) {
  return readArray(list, 500).map((chapter) => {
    const cleaned = { title: readString(chapter?.title, 300), start: readNumber(chapter?.start) };
    if (chapter.duration !== undefined) cleaned.duration = readNumber(chapter.duration);
    return cleaned;
  });
}

// Saves a transcript and/or chapters the extension read from YouTube. A missing field means it couldn't be
// fetched, so the saved copy is kept; a null transcript or empty chapter list means the video has none.
async function saveContent(env, videoId, request) {
  // Only accept data for videos the Worker has confirmed exist (when it first fetched their comments).
  const expiry = await db(env, "GET", `expiry/${videoId}`);
  if (!expiry?.comments && !expiry?.commentScan) throw new HttpError(409, "load the video's comments first");

  const body = await readJson(request);
  const now = Date.now();
  const updates = {};
  if (body.transcript !== undefined) {
    const transcript = cleanTranscript(body.transcript);
    updates[`videos/${videoId}/transcript`] = transcript && { ...transcript, fetchedAt: now };
    updates[`expiry/${videoId}/transcript`] = now;
  }
  if (body.chapters !== undefined) {
    for (const kind of ["creator", "auto"]) {
      const items = cleanChapters(body.chapters?.[kind]);
      updates[`videos/${videoId}/chapters/${kind}`] = items.length > 0 ? { fetchedAt: now, items } : null;
    }
    updates[`expiry/${videoId}/chapters`] = now;
  }
  if (Object.keys(updates).length > 0) await updatePaths(env, updates);
  return { saved: Object.keys(updates).filter((path) => path.startsWith("videos/")).length };
}

// ---------- POST /videos/{id}/notes ----------

async function addNotes(env, videoId, request) {
  const token = (request.headers.get("Authorization") ?? "").replace(/^Bearer /, "");
  const encoder = new TextEncoder();
  const [given, expected] = [encoder.encode(token), encoder.encode(env.NOTES_TOKEN ?? "")];
  if (!env.NOTES_TOKEN || given.length !== expected.length || !crypto.subtle.timingSafeEqual(given, expected)) {
    throw new HttpError(401, "wrong or missing NOTES_TOKEN");
  }

  const notes = readArray(await readJson(request), 200).map((note) => {
    const cleaned = {
      text: readString(note?.text, 1000),
      start: readNumber(note?.start),
      duration: readNumber(note?.duration, { positive: true }),
      createdAt: { ".sv": "timestamp" },
    };
    const author = readString(note.author, 100, { optional: true });
    if (author) cleaned.author = author;
    return cleaned;
  });

  // Random keys mean partners pushing at the same time never overwrite each other.
  const updates = {};
  const ids = notes.map((note) => {
    const id = crypto.randomUUID();
    updates[`videos/${videoId}/communityNotes/${id}`] = note;
    return id;
  });
  if (ids.length > 0) await updatePaths(env, updates);
  return { ids };
}

// ---------- Daily cleanup ----------

// Deletes YouTube data that hasn't been refreshed in 29 days. Community notes are never deleted.
async function deleteExpiredData(env) {
  const cutoff = Date.now() - RETENTION_MS;
  const updates = {};
  for (const [kind, paths] of Object.entries(EXPIRING_PATHS)) {
    // startAt=0 skips videos that don't have this kind of data at all.
    const expired = await db(env, "GET", "expiry", {
      query: { orderBy: JSON.stringify(kind), startAt: "0", endAt: String(cutoff), limitToFirst: "1000" },
    });
    for (const videoId of Object.keys(expired ?? {})) {
      for (const path of paths) updates[`videos/${videoId}/${path}`] = null;
      updates[`expiry/${videoId}/${kind}`] = null;
    }
  }

  const quota = await db(env, "GET", "quota", { query: { shallow: "true" } });
  for (const day of Object.keys(quota ?? {})) {
    if (day < quotaDay()) updates[`quota/${day}`] = null;
  }

  if (Object.keys(updates).length > 0) await updatePaths(env, updates);
  console.log(`cleanup removed ${Object.keys(updates).length} entries`);
}
