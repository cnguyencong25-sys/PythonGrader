(function () {
  const deviceStorageKey = "python-grader-exam-device-id";

  function createDeviceId() {
    const bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  }

  window.getExamDeviceId = function () {
    let deviceId = "";
    try {
      deviceId = localStorage.getItem(deviceStorageKey) || "";
    } catch (error) {
      // Fall back to tab storage when persistent storage is unavailable.
    }
    if (/^[a-f0-9]{32}$/i.test(deviceId)) return deviceId;

    try {
      deviceId = sessionStorage.getItem(deviceStorageKey) || "";
    } catch (error) {
      // Generate an in-memory identifier as a last resort.
    }
    if (/^[a-f0-9]{32}$/i.test(deviceId)) return deviceId;

    deviceId = createDeviceId();
    try {
      localStorage.setItem(deviceStorageKey, deviceId);
    } catch (error) {
      try {
        sessionStorage.setItem(deviceStorageKey, deviceId);
      } catch (storageError) {
        return deviceId;
      }
    }
    return deviceId;
  };

  window.rememberActiveExamSession = function (examId, sessionId) {
    try {
      localStorage.setItem(`python-grader-active-exam-${examId}`, String(sessionId));
      localStorage.setItem("python-grader-active-exam-session", String(sessionId));
    } catch (error) {
      try {
        sessionStorage.setItem(`python-grader-active-exam-${examId}`, String(sessionId));
        sessionStorage.setItem(
          "python-grader-active-exam-session",
          String(sessionId)
        );
      } catch (storageError) {
        return;
      }
    }
  };

  window.getRememberedActiveExamSessionId = function () {
    try {
      return localStorage.getItem("python-grader-active-exam-session") || "";
    } catch (error) {
      try {
        return sessionStorage.getItem("python-grader-active-exam-session") || "";
      } catch (storageError) {
        return "";
      }
    }
  };

  window.createExamEventToken = createDeviceId;

  window.getPendingExamFocusEventToken = function (sessionId) {
    const key = `python-grader-exam-focus-token-${sessionId}`;
    try {
      const eventToken = localStorage.getItem(key) || "";
      if (eventToken) return eventToken;
    } catch (error) {
      // Fall back to tab storage when persistent storage is unavailable.
    }
    try {
      return sessionStorage.getItem(key) || "";
    } catch (error) {
      return "";
    }
  };

  window.rememberPendingExamFocusEvent = function (sessionId, eventToken) {
    const key = `python-grader-exam-focus-token-${sessionId}`;
    try {
      localStorage.setItem(key, String(eventToken));
    } catch (error) {
      try {
        sessionStorage.setItem(key, String(eventToken));
      } catch (storageError) {
        return;
      }
    }
  };

  window.clearPendingExamFocusEvent = function (sessionId, expectedToken) {
    const key = `python-grader-exam-focus-token-${sessionId}`;
    if (
      expectedToken &&
      window.getPendingExamFocusEventToken(sessionId) !== expectedToken
    ) return;
    try {
      localStorage.removeItem(key);
    } catch (error) {
      // Continue by clearing tab storage as well.
    }
    try {
      sessionStorage.removeItem(key);
    } catch (error) {
      return;
    }
  };
})();
