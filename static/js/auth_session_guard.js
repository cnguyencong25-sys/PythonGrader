(function () {
  if (window.__authSessionGuardInstalled) return;
  window.__authSessionGuardInstalled = true;

  const originalFetch = window.fetch.bind(window);
  const legacyAuthStorageKeys = [
    "access_token",
    "refresh_token",
    "auth_token",
    "authToken",
  ];
  let redirecting = false;

  function clearLegacyAuthStorage() {
    ["localStorage", "sessionStorage"].forEach(storageName => {
      let storage;
      try {
        storage = window[storageName];
      } catch (error) {
        return;
      }
      if (!storage) return;
      legacyAuthStorageKeys.forEach(key => {
        try {
          storage.removeItem(key);
        } catch (error) {
          console.warn("Không thể xóa thông tin đăng nhập cũ.", error);
        }
      });
    });
  }

  function isApiRequest(input) {
    const requestUrl =
      typeof input === "string" || input instanceof URL ? input : input.url;
    const url = new URL(requestUrl, window.location.href);
    return url.origin === window.location.origin && url.pathname.startsWith("/api/");
  }

  window.handleSessionUnauthorized = function () {
    if (redirecting) return false;
    redirecting = true;
    clearLegacyAuthStorage();
    window.location.replace("/login?expired=token");
    return true;
  };

  window.fetch = async function (input, init) {
    const response = await originalFetch(input, init);
    if (!isApiRequest(input) || response.status < 400) return response;

    let data = {};
    try {
      data = await response.clone().json();
    } catch (error) {
      // Some error responses do not contain JSON.
    }

    if (
      response.status === 401 ||
      (data && data.msg === "Token has expired") ||
      (data && data.message === "Token has expired")
    ) {
      window.handleSessionUnauthorized();
    }
    return response;
  };
})();
