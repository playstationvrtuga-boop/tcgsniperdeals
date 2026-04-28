let deferredInstallPrompt = null;

function isNativeShell() {
  const capacitor = window.Capacitor;
  if (!capacitor) return false;
  if (typeof capacitor.isNativePlatform === "function") {
    return capacitor.isNativePlatform();
  }
  if (typeof capacitor.getPlatform === "function") {
    return capacitor.getPlatform() !== "web";
  }
  return false;
}

function isStandaloneWebApp() {
  return window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;
}

async function initNativeShell() {
  const nativeShell = isNativeShell();
  const installedWebApp = isStandaloneWebApp();
  if (!nativeShell && !installedWebApp) return;

  document.documentElement.classList.add("is-mobile-app-shell", "splash-skipped");
  document.body.classList.add("is-mobile-app-shell");

  if (!nativeShell) return;

  document.documentElement.classList.add("is-native-shell");
  document.body.classList.add("is-native-shell");

  try {
    const statusBar = window.Capacitor?.Plugins?.StatusBar;
    await statusBar?.setStyle?.({ style: "DARK" });
    await statusBar?.setBackgroundColor?.({ color: "#08111d" });
  } catch (error) {
    console.debug("Native status bar plugin not available yet.", error);
  }
}

function initSplash() {
  const splash = document.querySelector(".app-splash");
  if (!splash) return;

  const skipSplash = document.documentElement.classList.contains("splash-skipped");
  if (skipSplash) {
    splash.classList.add("is-hidden");
    return;
  }

  const hideSplash = () => {
    splash.classList.add("is-hidden");
    try {
      sessionStorage.setItem("tcgSplashSeen", "1");
    } catch (error) {}
  };

  window.setTimeout(hideSplash, 900);
  window.addEventListener("load", hideSplash, { once: true });
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

async function registerServiceWorker() {
  if (isNativeShell()) return null;
  if (!("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.register("/service-worker.js");
}

function setPushButtonsState({ enabled, active, blocked = false }) {
  document.querySelectorAll(".push-enable-button").forEach((button) => {
    button.dataset.pushState = blocked ? "blocked" : active ? "active" : enabled ? "ready" : "unavailable";

    if (!enabled) {
      button.disabled = true;
      button.textContent = "Get instant alerts";
      button.classList.remove("is-active", "is-blocked");
      return;
    }

    button.disabled = false;
    if (blocked) {
      button.textContent = "Alerts blocked";
    } else {
      button.textContent = active ? "Alerts active" : "Get instant alerts";
    }
    button.classList.toggle("is-active", active);
    button.classList.toggle("is-blocked", blocked);
  });
}

async function getPushState() {
  const emptyState = { enabled: false, active: false, blocked: false, registration: null, subscription: null, publicKey: "" };
  if (!document.querySelector(".push-enable-button")) return emptyState;
  if (isNativeShell()) return emptyState;
  if (!("Notification" in window) || !("serviceWorker" in navigator)) return emptyState;

  const infoResponse = await fetch("/push-info", { credentials: "same-origin" });
  if (!infoResponse.ok) return emptyState;

  const info = await infoResponse.json();
  if (!info.enabled || !info.publicKey) return emptyState;

  const registration = await registerServiceWorker();
  if (!registration) {
    return { ...emptyState, enabled: true, publicKey: info.publicKey, blocked: Notification.permission === "denied" };
  }

  const subscription = await registration.pushManager.getSubscription();
  return {
    enabled: true,
    active: Boolean(subscription),
    blocked: Notification.permission === "denied",
    registration,
    subscription,
    publicKey: info.publicKey,
  };
}

async function syncPushButtons() {
  try {
    const state = await getPushState();
    setPushButtonsState(state);
  } catch (error) {
    console.error(error);
    setPushButtonsState({ enabled: false, active: false, blocked: false });
  }
}

async function enablePush() {
  try {
    const state = await getPushState();
    if (!state.enabled) {
      alert("Instant alerts are not live yet.");
      return;
    }
    if (state.blocked) {
      alert("Browser notifications are blocked. Re-enable them in site or browser settings, then try again.");
      return;
    }
    if (!state.registration) {
      alert("This browser cannot complete push setup right now.");
      return;
    }

    let subscription = state.subscription;
    const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    if (permission !== "granted") {
      setPushButtonsState({ enabled: true, active: false, blocked: permission === "denied" });
      return;
    }

    if (!subscription) {
      subscription = await state.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(state.publicKey),
      });
    }

    const response = await fetch("/push-subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription),
    });
    if (!response.ok) {
      throw new Error("Push subscription could not be saved.");
    }

    setPushButtonsState({ enabled: true, active: true, blocked: false });
    alert("Instant VIP alerts enabled.");
  } catch (error) {
    console.error(error);
    alert("Could not enable instant VIP alerts.");
  }
}

async function disablePush() {
  try {
    const state = await getPushState();
    if (!state.registration) {
      setPushButtonsState({ enabled: false, active: false, blocked: false });
      return;
    }

    const endpoint = state.subscription?.endpoint;
    if (endpoint) {
      await fetch("/push-subscriptions", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint }),
      });
    }

    if (state.subscription) {
      await state.subscription.unsubscribe();
    }

    setPushButtonsState({ enabled: true, active: false, blocked: false });
    alert("Instant VIP alerts turned off.");
  } catch (error) {
    console.error(error);
    alert("Could not turn off instant VIP alerts.");
  }
}

async function togglePush() {
  if (isNativeShell()) {
    alert("Web push is handled in the PWA flow. Native app notifications need platform setup later.");
    return;
  }
  const state = await getPushState();
  if (!state.enabled) {
    alert("Instant alerts are not live yet.");
    return;
  }
  if (state.active) {
    await disablePush();
    return;
  }
  await enablePush();
}

async function toggleFavorite(button) {
  const listingId = button.dataset.listingId;
  if (!listingId) return;
  const response = await fetch(`/favorites/${listingId}`, { method: "POST" });
  const payload = await response.json();
  if (!payload.ok) return;
  button.classList.toggle("is-saved", payload.saved);
  button.textContent = payload.saved ? "Saved" : "Save";
}

function copyText(text) {
  if (!text) return Promise.resolve(false);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text).then(() => true).catch(() => false);
  }
  const probe = document.createElement("textarea");
  probe.value = text;
  probe.setAttribute("readonly", "");
  probe.style.position = "absolute";
  probe.style.left = "-9999px";
  document.body.appendChild(probe);
  probe.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(probe);
  return Promise.resolve(ok);
}

function initBilling() {
  const planCards = [...document.querySelectorAll("[data-plan-card]")];
  if (!planCards.length) return;

  const planButtons = [...document.querySelectorAll("[data-plan-select]")];
  const hiddenPlanInput = document.querySelector("[data-plan-hidden]");
  const selectedPlanName = document.querySelector("[data-selected-plan-name]");
  const selectedPlanPrice = document.querySelector("[data-selected-plan-price]");
  const selectedPlanSummary = document.querySelector("[data-selected-plan-summary]");
  const methodCards = [...document.querySelectorAll("[data-method-card]")];
  const methodSelect = document.querySelector("[data-payment-method-select]");
  const confirmToggle = document.querySelector("[data-confirm-toggle]");
  const confirmPanel = document.querySelector("[data-confirm-panel]");

  function setSelectedMethod(methodKey) {
    methodCards.forEach((card) => {
      card.classList.toggle("is-selected", card.dataset.method === methodKey);
    });
    if (methodSelect) methodSelect.value = methodKey;
  }

  function updateMethodLinks(selectedPlan) {
    const selectedPlanCard = planCards.find((card) => card.dataset.plan === selectedPlan);
    const selectedPlanNameText = selectedPlanCard?.querySelector(".plan-name")?.textContent?.trim() || selectedPlan;
    const selectedPlanPriceText = selectedPlanCard?.querySelector(".plan-price")?.textContent?.trim() || "";

    methodCards.forEach((card) => {
      const methodKey = card.dataset.method;
      const openButton = card.querySelector("[data-payment-open]");
      const planName = card.querySelector(`[data-payment-plan-name="${methodKey}"]`);
      const planPrice = card.querySelector(`[data-payment-plan-price="${methodKey}"]`);
      const planNote = card.querySelector(`[data-payment-plan-note="${methodKey}"]`);
      const copyButton = card.querySelector(`.copy-trigger[data-method="${methodKey}"]`);
      const methodName = openButton?.dataset.methodName || copyButton?.dataset.methodName || methodKey;
      if (!openButton) return;

      let links = {};
      try {
        links = JSON.parse(openButton.dataset.links || "{}");
      } catch (error) {}
      const nextLink = links[selectedPlan] || openButton.href;
      openButton.href = nextLink;
      openButton.textContent = `Open ${methodName}`;
      if (planName) planName.textContent = selectedPlanNameText;
      if (planPrice) planPrice.textContent = selectedPlanPriceText;
      if (planNote) {
        if (methodKey === "revolut") {
          planNote.textContent = `Open Revolut and send ${selectedPlanPriceText} with no fees.`;
        } else if (methodKey === "paypal") {
          planNote.textContent = "Open PayPal checkout for the selected access plan.";
        } else {
          planNote.textContent = `Opens the ${selectedPlanNameText.toLowerCase()} payment page automatically.`;
        }
      }
      if (copyButton) {
        copyButton.dataset.copyText = nextLink;
        copyButton.textContent = `Copy ${methodName} link`;
      }
    });
  }

  function setSelectedPlan(planKey) {
    const currentCard = planCards.find((card) => card.dataset.plan === planKey);
    if (!currentCard) return;

    planCards.forEach((card) => {
      const isSelected = card.dataset.plan === planKey;
      card.classList.toggle("is-selected", isSelected);
      const button = card.querySelector("[data-plan-select]");
      if (button) button.textContent = isSelected ? "Selected" : "Select plan";
    });

    const price = currentCard.querySelector(".plan-price")?.textContent?.trim() || "";
    const name = currentCard.querySelector(".plan-name")?.textContent?.trim() || "";

    if (hiddenPlanInput) hiddenPlanInput.value = planKey;
    if (selectedPlanName) selectedPlanName.textContent = name;
    if (selectedPlanPrice) selectedPlanPrice.textContent = price;
    if (selectedPlanSummary) selectedPlanSummary.textContent = `${name} - ${price}`;

    updateMethodLinks(planKey);
  }

  planButtons.forEach((button) => {
    button.addEventListener("click", () => setSelectedPlan(button.dataset.planSelect));
  });

  methodCards.forEach((card) => {
    card.addEventListener("click", (event) => {
      const actionTarget = event.target.closest("a, button");
      if (actionTarget) {
        setSelectedMethod(card.dataset.method);
        return;
      }
      setSelectedMethod(card.dataset.method);
    });
  });

  methodSelect?.addEventListener("change", () => setSelectedMethod(methodSelect.value));

  confirmToggle?.addEventListener("click", () => {
    confirmPanel?.classList.remove("is-hidden");
    confirmPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  const initialSelectedPlan = document.querySelector("[data-plan-card].is-selected")?.dataset.plan || planCards[0].dataset.plan;
  const initialMethod = methodSelect?.value || methodCards.find((card) => card.classList.contains("is-selected"))?.dataset.method || methodCards[0]?.dataset.method;
  setSelectedPlan(initialSelectedPlan);
  if (initialMethod) setSelectedMethod(initialMethod);
}

function htmlToElement(html) {
  if (!html) return null;
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

function formatFeedRelativeTime(input) {
  if (!input) return "";
  const detectedAt = new Date(input);
  if (Number.isNaN(detectedAt.getTime())) return "";

  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - detectedAt.getTime()) / 1000));
  if (elapsedSeconds < 10) return "Detected just now";
  if (elapsedSeconds < 60) return `Detected ${elapsedSeconds}s ago`;

  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) return `Detected ${elapsedMinutes}m ago`;

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `Detected ${elapsedHours}h ago`;

  const elapsedDays = Math.floor(elapsedHours / 24);
  return `Detected ${elapsedDays}d ago`;
}

function updateRelativeTimeLabels(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-relative-time][data-detected-at]").forEach((node) => {
    const nextText = formatFeedRelativeTime(node.dataset.detectedAt);
    if (nextText && node.textContent !== nextText) {
      node.textContent = nextText;
    }
  });
}

function createRadarController(radarRoot, enabled) {
  if (!radarRoot || !enabled) {
    return { pulse: () => {}, spawnPings: () => {} };
  }

  let pulseTimeout = null;
  function pulse() {
    if (pulseTimeout) window.clearTimeout(pulseTimeout);
    radarRoot.classList.remove("is-pulsing");
    void radarRoot.offsetWidth;
    radarRoot.classList.add("is-pulsing");
    pulseTimeout = window.setTimeout(() => {
      radarRoot.classList.remove("is-pulsing");
      pulseTimeout = null;
    }, 260);
  }

  function spawnPing(platformKey = "", delayMs = 0) {
    window.setTimeout(() => {
      if (!radarRoot.isConnected) return;
      const ping = document.createElement("span");
      ping.className = "live-radar-ping";

      const isVinted = String(platformKey || "").toLowerCase() === "vinted";
      const isEbay = String(platformKey || "").toLowerCase() === "ebay";
      const direction = isVinted ? -1 : isEbay ? 1 : Math.random() < 0.5 ? -1 : 1;
      const distance = 92 + Math.random() * 26;
      const drift = -16 + Math.random() * 32;

      ping.style.setProperty("--ping-dx", `${direction * distance}px`);
      ping.style.setProperty("--ping-dy", `${drift}px`);

      radarRoot.appendChild(ping);
      ping.classList.add("is-visible");
      ping.addEventListener(
        "animationend",
        () => {
          ping.remove();
        },
        { once: true }
      );
    }, delayMs);
  }

  function spawnPings(targets = 1) {
    if (Array.isArray(targets)) {
      targets.slice(0, 6).forEach((platformKey, index) => {
        spawnPing(platformKey, index * 72);
      });
      return;
    }

    const total = Math.max(1, Math.min(Number(targets) || 1, 6));
    for (let index = 0; index < total; index += 1) {
      spawnPing("", index * 72);
    }
  }

  return { pulse, spawnPings };
}

function createSourceController(sourceRail, enabled) {
  if (!sourceRail || !enabled) {
    return { pulsePlatforms: () => {} };
  }

  const sourceLabels = new Map(
    [...sourceRail.querySelectorAll("[data-source-label]")]
      .map((node) => [node.dataset.sourceLabel || "", node])
      .filter(([key, node]) => Boolean(key) && Boolean(node))
  );
  const activeTimers = new Map();

  function pulsePlatform(platformKey) {
    const pill = sourceLabels.get(platformKey);
    if (!pill) return;

    const existingTimer = activeTimers.get(platformKey);
    if (existingTimer) window.clearTimeout(existingTimer);

    pill.classList.remove("is-targeted");
    void pill.offsetWidth;
    pill.classList.add("is-targeted");

    const timer = window.setTimeout(() => {
      pill.classList.remove("is-targeted");
      activeTimers.delete(platformKey);
    }, 420);
    activeTimers.set(platformKey, timer);
  }

  function pulsePlatforms(platformKeys) {
    const uniqueKeys = [...new Set((platformKeys || []).filter(Boolean))];
    uniqueKeys.forEach((platformKey, index) => {
      window.setTimeout(() => pulsePlatform(platformKey), index * 70);
    });
  }

  return { pulsePlatforms };
}

function initLiveFeed() {
  const feedRoot = document.querySelector("[data-live-feed-root]");
  if (!feedRoot) return;

  const banner = document.querySelector("[data-feed-live-banner]");
  const bannerCopy = banner?.querySelector("[data-feed-live-banner-copy]");
  const bannerButton = banner?.querySelector("[data-feed-live-banner-button]");
  const radarRoot = document.querySelector("[data-live-radar]");
  const sourceRail = document.querySelector("[data-source-rail]");
  const radarLinkLeft = document.querySelector(".live-radar-link-left");
  const radarLinkRight = document.querySelector(".live-radar-link-right");
  const updatesUrl = feedRoot.dataset.feedUpdatesUrl;
  const pollIntervalMs = Number(feedRoot.dataset.feedPollMs || 2500);
  const deltaLimit = Number(feedRoot.dataset.feedDeltaLimit || 12);
  const radarEnabled = feedRoot.dataset.feedLiveRadar === "1";
  const targetFeedbackEnabled = feedRoot.dataset.feedTargetFeedback === "1";
  const cardAnimationsEnabled = feedRoot.dataset.feedCardAnimations === "1";
  const relativeTimeEnabled = feedRoot.dataset.feedRelativeTimeUpdates === "1";
  const relativeTimeIntervalMs = Number(feedRoot.dataset.feedRelativeTimeIntervalMs || 15000);
  const radar = createRadarController(radarRoot, radarEnabled);
  const sourceFeedback = createSourceController(sourceRail, radarEnabled && targetFeedbackEnabled);
  const linkTimers = new Map();

  const seenIds = new Set(
    [...feedRoot.querySelectorAll(".listing-card[data-listing-id]")]
      .map((card) => Number(card.dataset.listingId || 0))
      .filter(Boolean)
  );

  let latestDetectedAt = feedRoot.dataset.feedCursorDetectedAt || "";
  let latestId = Number(feedRoot.dataset.feedCursorId || 0);
  let unseenCount = 0;
  let timer = null;
  let inFlight = false;

  function normalizePlatformKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function playArrivalFeedback(items) {
    if (!items.length || !targetFeedbackEnabled) return;
    const platformKeys = items
      .map((item) => normalizePlatformKey(item?.platform_key || item?.platform))
      .filter(Boolean);

    radar.pulse();
    pulseRadarLinks(platformKeys);
    radar.spawnPings(platformKeys.length ? platformKeys : items.length || 1);
    window.setTimeout(() => {
      sourceFeedback.pulsePlatforms(platformKeys);
    }, 70);
  }

  function pulseRadarLinks(platformKeys) {
    const uniqueKeys = [...new Set((platformKeys || []).filter(Boolean))];
    const targets = new Set();
    uniqueKeys.forEach((platformKey) => {
      if (platformKey === "vinted") targets.add(radarLinkLeft);
      if (platformKey === "ebay") targets.add(radarLinkRight);
    });
    if (!targets.size) {
      targets.add(radarLinkLeft);
      targets.add(radarLinkRight);
    }

    targets.forEach((node) => {
      if (!node) return;
      const timerKey = node.className;
      const existingTimer = linkTimers.get(timerKey);
      if (existingTimer) window.clearTimeout(existingTimer);

      node.classList.remove("is-active");
      void node.offsetWidth;
      node.classList.add("is-active");

      const timer = window.setTimeout(() => {
        node.classList.remove("is-active");
        linkTimers.delete(timerKey);
      }, 520);
      linkTimers.set(timerKey, timer);
    });
  }

  function updateCursor(cursor) {
    if (!cursor) return;
    if (cursor.latest_detected_at) latestDetectedAt = cursor.latest_detected_at;
    if (cursor.latest_id) latestId = Number(cursor.latest_id) || latestId;
    feedRoot.dataset.feedCursorDetectedAt = latestDetectedAt;
    feedRoot.dataset.feedCursorId = String(latestId);
  }

  function setBannerCount(count) {
    if (!banner || !bannerCopy || !bannerButton) return;
    if (!count) {
      unseenCount = 0;
      banner.classList.add("is-hidden");
      banner.hidden = true;
      return;
    }

    banner.hidden = false;
    banner.classList.remove("is-hidden");
    bannerCopy.textContent = count === 1 ? "1 new deal ready" : `${count} new deals ready`;
    bannerButton.textContent = count === 1 ? "Jump to latest" : "Jump to latest";
  }

  function insertItems(items, preserveScroll = false) {
    if (!items.length) return;
    let totalHeight = 0;
    let insertedCount = 0;

    for (const item of [...items].reverse()) {
      const node = htmlToElement(item.html);
      if (!node) continue;
      const itemId = Number(item.id || node.dataset.listingId || 0);
      if (seenIds.has(itemId)) continue;
      if (item.detected_at) {
        node.dataset.detectedAt = item.detected_at;
        node.querySelectorAll("[data-relative-time]").forEach((label) => {
          label.dataset.detectedAt = item.detected_at;
        });
      }
      if (cardAnimationsEnabled) {
        node.classList.add("is-new-feed-item");
      }
      seenIds.add(itemId);
      feedRoot.insertBefore(node, feedRoot.firstChild);
      insertedCount += 1;
      if (preserveScroll) {
        totalHeight += node.getBoundingClientRect().height || 0;
      }
    }
    updateRelativeTimeLabels(feedRoot);
    if (preserveScroll && totalHeight > 0) {
      window.scrollBy({ top: totalHeight, left: 0, behavior: "auto" });
    }
    return insertedCount;
  }

  function isNearTop() {
    return window.scrollY < 220;
  }

  function scheduleNext(delayMs) {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(pollFeed, delayMs);
  }

  async function pollFeed() {
    if (inFlight || !updatesUrl) return;
    if (document.hidden) {
      scheduleNext(Math.max(pollIntervalMs, 10000));
      return;
    }

    inFlight = true;
    try {
      const url = new URL(updatesUrl, window.location.origin);
      if (latestDetectedAt && latestId) {
        url.searchParams.set("latest_detected_at", latestDetectedAt);
        url.searchParams.set("latest_id", String(latestId));
      }
      url.searchParams.set("limit", String(deltaLimit));

      const response = await fetch(url.toString(), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Feed polling failed (${response.status})`);
      }

      const data = await response.json();
      updateCursor(data.cursor);

      const items = Array.isArray(data.items) ? data.items : [];
      if (items.length) {
        playArrivalFeedback(items);
        window.setTimeout(() => {
          const insertedCount = insertItems(items, false);
          if (insertedCount) {
            setBannerCount(0);
          }
        }, cardAnimationsEnabled ? 140 : 0);
      }
    } catch (error) {
      console.debug("Live feed poll skipped:", error);
    } finally {
      inFlight = false;
      scheduleNext(pollIntervalMs);
    }
  }

  bannerButton?.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setBannerCount(0);
  });

  let scrollThrottle = null;
  window.addEventListener(
    "scroll",
    () => {
      if (scrollThrottle) return;
      scrollThrottle = window.setTimeout(() => {
        scrollThrottle = null;
        if (isNearTop()) setBannerCount(0);
      }, 120);
    },
    { passive: true }
  );

  setBannerCount(0);
  scheduleNext(pollIntervalMs);

  if (relativeTimeEnabled) {
    updateRelativeTimeLabels(feedRoot);
    window.setInterval(() => {
      updateRelativeTimeLabels(feedRoot);
    }, Math.max(5000, relativeTimeIntervalMs));
  }
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  const installButton = document.querySelector(".install-button");
  if (installButton) installButton.hidden = false;
});

document.addEventListener("click", async (event) => {
  const favoriteButton = event.target.closest(".favorite-toggle");
  if (favoriteButton) {
    event.preventDefault();
    toggleFavorite(favoriteButton);
    return;
  }

  const installButton = event.target.closest(".install-button");
  if (installButton) {
    if (!deferredInstallPrompt) {
      const fallbackUrl = installButton.dataset.fallbackUrl;
      if (fallbackUrl) window.location.href = fallbackUrl;
      return;
    }
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    return;
  }

  const pushButton = event.target.closest(".push-enable-button");
  if (pushButton && !pushButton.disabled) {
    togglePush();
    return;
  }

  const copyButton = event.target.closest(".copy-trigger");
  if (copyButton) {
    const methodName = copyButton.dataset.methodName || "payment";
    const originalLabel = `Copy ${methodName} link`;
    const copied = await copyText(copyButton.dataset.copyText);
    copyButton.textContent = copied ? "Copied" : "Copy failed";
    window.setTimeout(() => {
      copyButton.textContent = originalLabel;
    }, 1400);
  }
});

initNativeShell().finally(() => {
  registerServiceWorker();
  syncPushButtons();
  initSplash();
  initBilling();
  initLiveFeed();
});
