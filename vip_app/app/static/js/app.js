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

async function initNativeShell() {
  if (!isNativeShell()) return;

  document.documentElement.classList.add("is-native-shell", "splash-skipped");
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
      button.textContent = "Instant alerts unavailable";
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
  if (installButton && deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.hidden = true;
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
});
