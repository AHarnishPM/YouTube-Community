importScripts("endpoints.js", "consent.js");

const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;

async function callWorker(videoId, path = "", options = {}) {
  if (!VIDEO_ID_PATTERN.test(videoId)) throw new Error(`invalid video id: ${videoId}`);
  const res = await fetch(`${WORKER_URL}/videos/${videoId}${path}`, options);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(`server error ${res.status}: ${body?.error ?? "no details"}`);
  return body;
}

const messageHandlers = {
  getVideo: ({ videoId }) => callWorker(videoId),
  saveContent: ({ videoId, transcript, chapters }) =>
    callWorker(videoId, "/content", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, chapters }),
    }),
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = messageHandlers[message.type];
  if (!handler) return;
  // Nothing is sent to the server until the user has agreed to the privacy policy.
  hasConsent()
    .then((consented) => {
      if (!consented) throw new Error("the privacy policy hasn't been accepted yet");
      return handler(message);
    })
    .then(
      (value) => sendResponse({ ok: true, value }),
      (err) => sendResponse({ ok: false, error: err.message })
    );
  return true;
});

chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === "install") chrome.tabs.create({ url: "welcome.html" });
});
