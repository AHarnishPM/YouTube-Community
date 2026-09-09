(function () {
  const BUBBLE_ID = "ytc-hello-bubble";

  function injectBubble() {
    if (document.getElementById(BUBBLE_ID)) return;

    const timeDisplay = document.querySelector(".ytp-time-display");
    if (!timeDisplay) return;

    const bubble = document.createElement("span");
    bubble.id = BUBBLE_ID;
    bubble.className = "ytc-bubble";

    const inner = document.createElement("span");
    inner.className = "ytc-bubble-inner";
    inner.textContent = "Hello World";
    bubble.appendChild(inner);

    timeDisplay.insertAdjacentElement("afterend", bubble);
  }

  const observer = new MutationObserver(injectBubble);
  observer.observe(document.body, { childList: true, subtree: true });

  injectBubble();
})();
