(() => {
  const offlineBanner = document.getElementById("offline-banner");
  const installBanner = document.getElementById("install-banner");
  const installButton = document.getElementById("install-button");
  const installDismiss = document.getElementById("install-dismiss");

  function setOffline(offline) {
    if (!offlineBanner) {
      return;
    }
    offlineBanner.hidden = !offline;
  }

  setOffline(!navigator.onLine);
  window.addEventListener("online", () => setOffline(false));
  window.addEventListener("offline", () => setOffline(true));

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") {
      return;
    }
    if (navigator.onLine) {
      return;
    }
    event.preventDefault();
    window.location.href = "/offline";
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }

  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (installBanner) {
      installBanner.hidden = false;
    }
  });

  installButton?.addEventListener("click", async () => {
    if (!deferredPrompt) {
      return;
    }
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    if (installBanner) {
      installBanner.hidden = true;
    }
  });

  installDismiss?.addEventListener("click", () => {
    if (installBanner) {
      installBanner.hidden = true;
    }
  });
})();
