(function () {
  const examWorkspace = document.querySelector(".workspace-layout");
  const isExamWorkspace =
    window.location.pathname === "/student/exam-workspace" &&
    examWorkspace &&
    examWorkspace.dataset.sessionType !== "free";
  const isPracticeWorkspace =
    window.location.pathname === "/student/workspace" ||
    window.location.pathname === "/student/free-practice-workspace";

  if (isPracticeWorkspace) return;

  const currentUrl = new URL(window.location.href);
  const startupReason = currentUrl.searchParams.get("fresh_exam") === "1"
    || currentUrl.searchParams.get("device_changed") === "1"
    || currentUrl.searchParams.get("resume_warning") === "1";

  async function prepareExamResume() {
    if (startupReason) {
      if (currentUrl.searchParams.has("fresh_exam")) {
        currentUrl.searchParams.delete("fresh_exam");
        window.history.replaceState({}, "", currentUrl);
      }
      return true;
    }

    const rememberedSessionId = isExamWorkspace
      ? examWorkspace.dataset.sessionId
      : window.getRememberedActiveExamSessionId();
    const focusEventToken = rememberedSessionId
      ? window.getPendingExamFocusEventToken(rememberedSessionId)
      : "";

    try {
      const response = await fetch("/api/student/exams/active-session", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: window.getExamDeviceId(),
          prior_focus_event_token: focusEventToken || null,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        await window.showAppAlert(
          data.message || "Không kiểm tra được bài thi đang làm dở."
        );
        return true;
      }
      if (!data.active) return true;

      window.rememberActiveExamSession(data.exam_id, data.session_id);
      if (focusEventToken) {
        window.clearPendingExamFocusEvent(
          rememberedSessionId,
          focusEventToken
        );
      }

      const target = new URL("/student/exam-workspace", window.location.origin);
      target.searchParams.set("session_id", String(data.session_id));
      if (data.anti_cheat_enabled) {
        target.searchParams.set("resume_warning", "1");
      }

      if (
        isExamWorkspace &&
        Number(examWorkspace.dataset.sessionId) === Number(data.session_id)
      ) {
        window.history.replaceState({}, "", target);
        return true;
      }

      window.location.replace(target);
      return false;
    } catch (error) {
      console.error("Không thể khôi phục bài thi đang làm dở.", error);
      await window.showAppAlert(
        "Không thể kết nối để kiểm tra bài thi đang làm dở. Vui lòng thử tải lại trang."
      );
      return true;
    }
  }

  if (isExamWorkspace) {
    window.examResumeReady = prepareExamResume();
  } else {
    prepareExamResume();
  }
})();
