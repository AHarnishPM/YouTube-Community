document.getElementById("privacy-link").href = `${WORKER_URL}/privacy`;

async function showState() {
  const consented = await hasConsent();
  document.getElementById("agree").hidden = consented;
  document.getElementById("done").hidden = !consented;
}
showState();

document.getElementById("agree").addEventListener("click", async () => {
  await giveConsent();
  showState();
});
