(function () {
  let overlay = null;
  let messageElement = null;
  let confirmButton = null;
  let activeResolver = null;
  let previousFocus = null;
  const pendingAlerts = [];

  function closeAlert() {
    if (!activeResolver) return;
    const resolve = activeResolver;
    activeResolver = null;
    overlay.hidden = true;
    resolve();
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus();
    }
    showNextAlert();
  }

  function createAlert() {
    overlay = document.createElement("div");
    overlay.className = "app-alert-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <section class="app-alert-dialog" role="alertdialog" aria-modal="true"
               aria-labelledby="appAlertTitle" aria-describedby="appAlertMessage">
        <h2 id="appAlertTitle">Thông báo</h2>
        <p id="appAlertMessage"></p>
        <button class="app-alert-confirm" type="button">Xác nhận</button>
      </section>
    `;
    document.body.appendChild(overlay);
    messageElement = overlay.querySelector("#appAlertMessage");
    confirmButton = overlay.querySelector(".app-alert-confirm");
    confirmButton.addEventListener("click", closeAlert);
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && activeResolver) closeAlert();
    });
  }

  function showNextAlert() {
    if (activeResolver || pendingAlerts.length === 0) return;
    const alert = pendingAlerts.shift();
    previousFocus = document.activeElement;
    messageElement.textContent = alert.message;
    activeResolver = alert.resolve;
    overlay.hidden = false;
    confirmButton.focus();
  }

  window.showAppAlert = function (message) {
    if (!overlay) createAlert();
    return new Promise(resolve => {
      pendingAlerts.push({
        message: String(message == null ? "" : message),
        resolve,
      });
      showNextAlert();
    });
  };
})();
