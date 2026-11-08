// Usage: NOTES_TOKEN=... node scripts/push-notes.mjs <videoId> <notes.json>
import { readFileSync } from "node:fs";

const [videoId, notesPath] = process.argv.slice(2);
const token = process.env.NOTES_TOKEN;
if (!videoId || !notesPath || !token) {
  console.error("Usage: NOTES_TOKEN=... node scripts/push-notes.mjs <videoId> <notes.json>");
  process.exit(1);
}

const endpointsSource = readFileSync(new URL("../endpoints.js", import.meta.url), "utf8");
const workerUrl = new Function(`${endpointsSource}\nreturn WORKER_URL;`)();
const notes = JSON.parse(readFileSync(notesPath, "utf8"));

const res = await fetch(`${workerUrl}/videos/${videoId}/notes`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  body: JSON.stringify(notes),
});
const body = await res.json().catch(() => null);
if (!res.ok) {
  console.error(`Failed to add notes: ${res.status} ${body?.error ?? ""}`);
  process.exit(1);
}
body.ids.forEach((id, i) => console.log(`Added ${id} (${notes[i].start}s for ${notes[i].duration}s): ${notes[i].text}`));
