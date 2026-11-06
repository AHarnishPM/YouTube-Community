// Usage: node scripts/push-notes.mjs <videoId> <notes.json>
import { readFileSync } from "node:fs";

const [videoId, notesPath] = process.argv.slice(2);
if (!videoId || !notesPath) {
  console.error("Usage: node scripts/push-notes.mjs <videoId> <notes.json>");
  process.exit(1);
}

const configSource = readFileSync(new URL("../config.js", import.meta.url), "utf8");
const { apiKey, databaseURL } = new Function(`${configSource}\nreturn FIREBASE_CONFIG;`)();
const notes = JSON.parse(readFileSync(notesPath, "utf8"));

const signIn = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${apiKey}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ returnSecureToken: true }),
});
if (!signIn.ok) throw new Error(`Firebase sign-in failed: ${signIn.status} ${await signIn.text()}`);
const { idToken } = await signIn.json();

const notesUrl = `${databaseURL}/videos/${videoId}/communityNotes.json?auth=${encodeURIComponent(idToken)}`;
for (const note of notes) {
  // POST gives each note a unique key, so partners pushing at the same time never overwrite each other.
  const res = await fetch(notesUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...note, createdAt: { ".sv": "timestamp" } }),
  });
  if (!res.ok) {
    console.error(`Failed to add "${note.text}": ${res.status} ${await res.text()}`);
    process.exitCode = 1;
    continue;
  }
  const { name } = await res.json();
  console.log(`Added ${name} (${note.start}s for ${note.duration}s): ${note.text}`);
}
