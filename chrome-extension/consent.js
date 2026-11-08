// Shared by the background worker, content script, popup, and welcome page.
const CONSENT_KEY = "consentedAt";

async function hasConsent() {
  const { [CONSENT_KEY]: consentedAt } = await chrome.storage.local.get(CONSENT_KEY);
  return Boolean(consentedAt);
}

const giveConsent = () => chrome.storage.local.set({ [CONSENT_KEY]: Date.now() });
const withdrawConsent = () => chrome.storage.local.remove(CONSENT_KEY);
