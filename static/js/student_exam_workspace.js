async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (!isFreeSession && deviceId) {
    opts.headers["X-Exam-Device-Id"] = deviceId;
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const wsLayout = document.querySelector(".workspace-layout");
const sessionId = wsLayout.dataset.sessionId;
const isFreeSession = wsLayout.dataset.sessionType === "free";
const deviceId = isFreeSession ? null : window.getExamDeviceId();
const sessionApi = isFreeSession
  ? `/api/student/free-sessions/${sessionId}`
  : `/api/student/exam-sessions/${sessionId}`;
const returnUrl = isFreeSession ? "/student/chapters" : "/student/exams";

let exercises = [];
let currentExIndex = -1;
let editor = null;
let submissionsData = {};
let autoSaveTimeout = null;
let timerInterval = null;
let runInputs = [];
let previousRunOutput = "";
let runTranscript = "";
let runGeneration = 0;
let autoFinishInProgress = false;
let examFinished = false;
let proctoringTimer = null;
let proctoringCheckInFlight = false;
let proctoringExitHandled = false;
let focusDebounceTimer = null;
let focusAway = false;
let antiCheatEnabled = false;

// 1. KHỞI TẠO EDITOR
function initEditor() {
  editor = createStudentCodeEditor(document.getElementById("codeEditor"), {
    mode: "python", theme: "dracula", lineNumbers: false,
    autoCloseBrackets: true, indentUnit: 4, tabSize: 4,
  });
  editor.setSize("100%", "100%");
  editor.on("change", () => {
    if (currentExIndex === -1) return;
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(autoSaveDraft, 1500);
  });
}

// 2. LƯU NHÁP
async function autoSaveDraft() {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  await fetchJSON(`${sessionApi}/save-draft`, {
    method: "POST", body: JSON.stringify({ exercise_id: ex.id, code: editor.getValue() })
  });
}

function saveDraftOnPageHide() {
  if (isFreeSession || examFinished || currentExIndex < 0 || !editor) return;
  const exercise = exercises[currentExIndex];
  if (!exercise) return;

  const body = JSON.stringify({
    exercise_id: exercise.id,
    code: editor.getValue(),
  });
  const url = `${sessionApi}/save-draft`;
  const payload = new Blob([body], { type: "application/json" });
  if (navigator.sendBeacon && navigator.sendBeacon(url, payload)) return;

  fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(error => {
    console.error("Không thể lưu bản nháp khi rời bài thi.", error);
  });
}

window.addEventListener("pagehide", saveDraftOnPageHide);

function restoreOfficialExamNavigation() {
  if (isFreeSession) return;
  const studentLayout = document.querySelector(".student-layout");
  if (studentLayout) studentLayout.classList.remove("official-exam-workspace");
}

// 3. LOAD WORKSPACE & BẮT ĐẦU ĐẾM NGƯỢC
async function loadWorkspace() {
  const { ok, data } = await fetchJSON(sessionApi);
  
  if (!ok || !data.success) {
    const message = data.blocked
      ? "Bài thi đã bị giáo viên đình chỉ. Điểm bài thi được chốt 0."
      : data.message || "Lỗi tải dữ liệu hoặc đã hết giờ.";
    restoreOfficialExamNavigation();
    await window.showAppAlert(message);
    window.location.href = returnUrl;
    return;
  }

  exercises = data.exam.exercises;
  submissionsData = data.submissions || {};
  antiCheatEnabled = Boolean(data.exam.anti_cheat_enabled);

  renderExerciseGrid();
  if (exercises.length > 0) selectExercise(0);

  if (data.remain_seconds === null || data.remain_seconds === undefined) {
    document.getElementById("timerDisplay").hidden = true;
  } else {
    startCountdown(data.remain_seconds);
  }

  if (!isFreeSession) {
    const workspaceUrl = new URL(window.location.href);
    const wasResumed = workspaceUrl.searchParams.get("resume_warning") === "1";
    const deviceChanged = workspaceUrl.searchParams.get("device_changed") === "1";
    if (deviceChanged || wasResumed) {
      workspaceUrl.searchParams.delete("device_changed");
      workspaceUrl.searchParams.delete("resume_warning");
      window.history.replaceState({}, "", workspaceUrl);
      if (antiCheatEnabled) {
        await window.showAppAlert(wasResumed
          ? "Hệ thống đã ghi nhận bạn rời khỏi màn hình thi hoặc đăng nhập lại trong lúc làm bài. Cần nghiêm túc làm bài!"
          : "Hệ thống đã ghi nhận bạn đã đăng nhập thêm ở một thiết bị khác. Cần nghiêm túc làm bài!"
        );
      }
    }
    if (antiCheatEnabled) startExamProctoring();
  }
}

async function handleExamProctoringExit(message, redirectToLogin = false) {
  if (proctoringExitHandled) return;
  proctoringExitHandled = true;
  examFinished = true;
  clearInterval(timerInterval);
  clearInterval(proctoringTimer);
  clearTimeout(focusDebounceTimer);
  document.removeEventListener("visibilitychange", handleExamVisibilityChange);
  window.removeEventListener("blur", scheduleFocusViolation);
  window.removeEventListener("focus", clearFocusViolation);
  window.removeEventListener("pagehide", saveDraftOnPageHide);
  restoreOfficialExamNavigation();
  await window.showAppAlert(message);
  window.location.href = redirectToLogin ? "/login?expired=another_login" : returnUrl;
}

async function checkExamProctoringStatus() {
  if (isFreeSession || !antiCheatEnabled || examFinished || proctoringCheckInFlight) return;
  proctoringCheckInFlight = true;
  try {
    const { ok, data } = await fetchJSON(`${sessionApi}/status`);
    if (!ok) {
      if (data.reason === "device_replaced" || data.reason === "session_replaced") {
        await handleExamProctoringExit(data.message || "Phiên thi đã được thay thế.");
      } else if (data.reason && data.reason.startsWith("revoked:")) {
        await handleExamProctoringExit(
          "Phiên đăng nhập đã được sử dụng trên thiết bị khác.",
          true
        );
      }
      return;
    }
    if (data.is_blocked) {
      await handleExamProctoringExit(
        "Bài thi đã bị giáo viên đình chỉ. Điểm bài thi được chốt 0."
      );
    } else if (data.is_finalized) {
      examFinished = true;
      clearInterval(proctoringTimer);
    }
  } catch (error) {
    console.error("Không thể kiểm tra trạng thái giám sát bài thi.", error);
  } finally {
    proctoringCheckInFlight = false;
  }
}

function startExamProctoring() {
  if (isFreeSession || !antiCheatEnabled || examFinished) return;
  checkExamProctoringStatus();
  proctoringTimer = setInterval(checkExamProctoringStatus, 3000);
  document.addEventListener("visibilitychange", handleExamVisibilityChange);
  window.addEventListener("blur", scheduleFocusViolation);
  window.addEventListener("focus", clearFocusViolation);
}

function handleExamVisibilityChange() {
  if (document.hidden) scheduleFocusViolation();
  else clearFocusViolation();
}

function scheduleFocusViolation() {
  if (isFreeSession || !antiCheatEnabled || examFinished || focusAway || proctoringExitHandled) return;
  focusAway = true;
  focusDebounceTimer = setTimeout(() => {
    focusDebounceTimer = null;
    if (document.hidden || !document.hasFocus()) {
      recordFocusViolation();
    } else {
      focusAway = false;
    }
  }, 400);
}

function clearFocusViolation() {
  if (focusDebounceTimer) {
    clearTimeout(focusDebounceTimer);
    focusDebounceTimer = null;
  }
  focusAway = false;
}

async function recordFocusViolation() {
  let syncFailed = false;
  const eventToken = window.createExamEventToken();
  window.rememberPendingExamFocusEvent(sessionId, eventToken);
  try {
    const { ok, data } = await fetchJSON(`${sessionApi}/abnormal-event`, {
      method: "POST",
      body: JSON.stringify({
        event_type: "focus_leave",
        event_token: eventToken,
      }),
    });
    if (!ok || !data.success) {
      syncFailed = true;
    }
  } catch (error) {
    syncFailed = true;
  }

  await window.showAppAlert(
    "Hệ thống đã ghi nhận bạn rời khỏi màn hình thi. Cần nghiêm túc làm bài!"
  );
  if (syncFailed) {
    await window.showAppAlert(
      "Không thể đồng bộ lần vi phạm lên máy chủ. Hãy kiểm tra kết nối mạng."
    );
  }
  if (!syncFailed) {
    window.clearPendingExamFocusEvent(sessionId, eventToken);
  }
}

function renderExerciseGrid() {
  const grid = document.getElementById("exerciseGrid");
  grid.innerHTML = exercises.map((ex, i) => {
    let statusClass = "";
    if (submissionsData[ex.id] && submissionsData[ex.id].status !== "pending") {
      statusClass = submissionsData[ex.id].status;
    }
    return `<button class="ex-btn ${statusClass}" data-index="${i}">${i + 1}</button>`;
  }).join("");

  document.querySelectorAll(".ex-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      autoSaveDraft().then(() => selectExercise(parseInt(btn.dataset.index)));
    });
  });
}

function selectExercise(index) {
  currentExIndex = index;
  const ex = exercises[index];
  document.getElementById("nextQuestionBtn").disabled = index >= exercises.length - 1;

  document.querySelectorAll(".ex-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelector(`.ex-btn[data-index="${index}"]`).classList.add("active");

  document.getElementById("problemBody").style.display = "flex";
  document.getElementById("problemTitle").textContent = `Bài ${index + 1}: ${ex.title}`;
  document.getElementById("problemDescription").textContent = ex.description;
  document.getElementById("problemOutputFormat").textContent = ex.output_format || "(Không có)";
  document.getElementById("problemConstraints").textContent = ex.constraints || "(Không có)";
  renderStudentSampleCases(ex);
  resetRunPanel();

  if (submissionsData[ex.id] && submissionsData[ex.id].code) {
    editor.setValue(submissionsData[ex.id].code);
    if (submissionsData[ex.id].status !== "pending") updateSubmitResultUI(submissionsData[ex.id]);
    else document.getElementById("submitResult").textContent = "";
  } else {
    editor.setValue("");
    document.getElementById("submitResult").textContent = "";
  }
}

function resetRunPanel() {
  runGeneration += 1;
  runInputs = [];
  previousRunOutput = "";
  runTranscript = "";
  document.getElementById("runInputForm").hidden = true;
  document.getElementById("runOutput").hidden = false;
  document.getElementById("runInputTranscript").textContent = "";
  document.getElementById("runInput").value = "";
  document.getElementById("runCodeBtn").disabled = false;
  document.getElementById("runCodeBtn").textContent = "Chạy thử";
  document.getElementById("runOutput").textContent = "";
  document.getElementById("runStatus").textContent = "";
}

async function executeCurrentCode() {
  if (currentExIndex === -1) return;
  const generation = runGeneration;
  const ex = exercises[currentExIndex];
  const button = document.getElementById("runCodeBtn");
  const output = document.getElementById("runOutput");
  const status = document.getElementById("runStatus");
  const inputForm = document.getElementById("runInputForm");
  const inputField = document.getElementById("runInput");
  button.disabled = true;
  button.textContent = "Đang chạy...";

  try {
    const { ok, data } = await fetchJSON(`${sessionApi}/run`, {
      method: "POST",
      body: JSON.stringify({
        exercise_id: ex.id,
        code: editor.getValue(),
        input: runInputs.length ? `${runInputs.join("\n")}\n` : "",
      }),
    });
    if (generation !== runGeneration) return;
    if (!ok || !data.success) {
      runTranscript = [runTranscript, data.message || "Không chạy được code."]
        .filter(Boolean).join("\n");
      output.textContent = runTranscript;
      inputForm.hidden = true;
      output.hidden = false;
      document.getElementById("runInputTranscript").textContent = "";
      status.textContent = "Lỗi";
      return;
    }

    const stdout = data.stdout || "";
    if (previousRunOutput && stdout.startsWith(previousRunOutput)) {
      runTranscript += stdout.slice(previousRunOutput.length);
    } else if (runInputs.length) {
      runTranscript += stdout;
    } else {
      runTranscript = stdout;
    }
    output.textContent = runTranscript;
    if (data.output_truncated) output.textContent += "\n\n(Output đã được rút gọn)";
    if (data.needs_input) {
      previousRunOutput = stdout;
      document.getElementById("runInputTranscript").textContent = runTranscript;
      inputForm.hidden = false;
      output.hidden = true;
      document.getElementById("runPrompt").textContent = "Nhập input, nhấn Enter để gửi";
      status.textContent = "Chương trình đang chờ input";
      inputField.focus();
    } else {
      previousRunOutput = "";
      inputForm.hidden = true;
      output.hidden = false;
      document.getElementById("runInputTranscript").textContent = "";
      if (data.stderr) {
        runTranscript += `${runTranscript ? "\n" : ""}Lỗi chạy chương trình:\n${data.stderr}`;
        output.textContent = runTranscript;
      }
      status.textContent = data.timed_out ? "Quá thời gian" : data.stderr ? "Có lỗi" : "Hoàn tất";
    }
  } catch (error) {
    if (generation !== runGeneration) return;
    runTranscript = [runTranscript, "Không kết nối được máy chủ. Vui lòng thử lại."]
      .filter(Boolean).join("\n");
    output.textContent = runTranscript;
    inputForm.hidden = true;
    output.hidden = false;
    document.getElementById("runInputTranscript").textContent = "";
    status.textContent = "Lỗi kết nối";
  } finally {
    if (generation === runGeneration) {
      button.disabled = false;
      button.textContent = "Chạy thử";
    }
  }
}

async function runCurrentCode() {
  const inputForm = document.getElementById("runInputForm");
  if (!inputForm.hidden) {
    inputForm.requestSubmit();
    return;
  }
  runGeneration += 1;
  runInputs = [];
  previousRunOutput = "";
  runTranscript = "";
  document.getElementById("runInput").value = "";
  inputForm.hidden = true;
  document.getElementById("runOutput").hidden = false;
  document.getElementById("runInputTranscript").textContent = "";
  document.getElementById("runOutput").textContent = "";
  document.getElementById("runStatus").textContent = "";
  await executeCurrentCode();
}

function clearRunConsole() {
  runTranscript = "";
  document.getElementById("runOutput").textContent = "";
  document.getElementById("runInputTranscript").textContent = "";
  document.getElementById("runStatus").textContent = "";
  document.getElementById("runInput").value = "";
}

document.getElementById("runInputForm").addEventListener("submit", async event => {
  event.preventDefault();
  const inputField = document.getElementById("runInput");
  runInputs.push(inputField.value);
  runTranscript += `${inputField.value}\n`;
  inputField.value = "";
  document.getElementById("runInputForm").hidden = true;
  document.getElementById("runOutput").hidden = false;
  await executeCurrentCode();
});

document.getElementById("runInput").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.getElementById("runInputForm").requestSubmit();
  }
});

function updateSubmitResultUI(result) {
  const resEl = document.getElementById("submitResult");
  if (result.status === "correct") {
    resEl.textContent = "Đúng hoàn toàn";
    resEl.className = "submit-result correct";
  } else if (result.status === "partial") {
    resEl.textContent = "Đúng một phần";
    resEl.className = "submit-result partial";
  } else {
    resEl.textContent = "Sai";
    resEl.className = "submit-result wrong";
  }
}

// 4. NỘP BÀI TỪNG CÂU
document.getElementById("submitBtn").addEventListener("click", async () => {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const btn = document.getElementById("submitBtn");
  btn.disabled = true; btn.textContent = "Đang chấm...";

  try {
    const { ok, data } = await fetchJSON(`${sessionApi}/submit`, {
      method: "POST", body: JSON.stringify({ exercise_id: ex.id, code: editor.getValue() })
    });

    if (ok && data.success) {
      const result = data.result;
      submissionsData[ex.id] = result;
      
      const exBtn = document.querySelector(`.ex-btn[data-index="${currentExIndex}"]`);
      exBtn.classList.remove("correct", "partial", "wrong");
      if(result.status !== "pending") exBtn.classList.add(result.status);

      updateSubmitResultUI(result);
    } else {
      await window.showAppAlert(data.message || "Lỗi nộp bài.");
    }
  } catch (err) {
    await window.showAppAlert("Lỗi kết nối máy chủ.");
  } finally {
    btn.disabled = false; btn.textContent = "Nộp bài";
  }
});

document.getElementById("nextQuestionBtn").addEventListener("click", async () => {
  if (currentExIndex < 0 || currentExIndex >= exercises.length - 1) return;

  const btn = document.getElementById("nextQuestionBtn");
  const nextIndex = currentExIndex + 1;
  btn.disabled = true;
  clearTimeout(autoSaveTimeout);
  try {
    await autoSaveDraft();
    selectExercise(nextIndex);
  } catch (error) {
    await window.showAppAlert("Không lưu được bản nháp. Vui lòng thử lại.");
  } finally {
    btn.disabled = currentExIndex >= exercises.length - 1;
  }
});
document.getElementById("runCodeBtn").addEventListener("click", runCurrentCode);
document.getElementById("clearRunOutputBtn").addEventListener("click", clearRunConsole);

// 5. ĐỒNG HỒ ĐẾM NGƯỢC (QUAN TRỌNG)
function startCountdown(totalSeconds) {
  const timerText = document.getElementById("timeText");
  const timerBox = document.getElementById("timerDisplay");
  let remain = Math.max(0, totalSeconds);
  const renderTime = () => {
    const m = Math.floor(remain / 60).toString().padStart(2, '0');
    const s = (remain % 60).toString().padStart(2, '0');
    timerText.textContent = `${m}:${s}`;
  };
  renderTime();

  if (remain <= 0) {
    forceFinishExam();
    return;
  }

  timerInterval = setInterval(async () => {
    remain = Math.max(0, remain - 1);
    renderTime();

    // Cảnh báo khi còn < 5 phút
    if (remain <= 300) timerBox.classList.add("warning");

    // Hết giờ -> Tự động nộp
    if (remain <= 0) {
      clearInterval(timerInterval);
      await window.showAppAlert("Đã hết thời gian làm bài. Hệ thống tự động nộp bài.");
      forceFinishExam();
    }
  }, 1000);
}

// 6. KẾT THÚC BÀI THI
function showFinishModal(isAuto = false) {
  const listEl = document.getElementById("summaryList");
  listEl.innerHTML = exercises.map((ex, i) => {
    const submission = submissionsData[ex.id];
    const status = submission && ["correct", "partial", "wrong"].includes(submission.status)
      ? submission.status
      : "pending";
    const statusText = {
      correct: "Đúng",
      partial: "Đúng một phần",
      wrong: "Sai",
      pending: "Chưa nộp",
    }[status];
    return `<div class="summary-item status-${status}">
        <span>Bài ${i + 1}: ${ex.title}</span>
        <strong>${statusText}</strong>
      </div>`;
  }).join("");

  if(isAuto) {
    document.getElementById("modalTitle").textContent = "Đã hết giờ làm bài";
    document.getElementById("cancelFinishBtn").style.display = "none"; // Không cho tiếp tục
  } else {
    document.getElementById("modalTitle").textContent = "Xác nhận nộp bài";
    document.getElementById("cancelFinishBtn").style.display = "inline-block";
  }

  document.getElementById("summaryStep").style.display = "block";
  document.getElementById("scoreStep").style.display = "none";
  document.getElementById("finishModal").classList.remove("hidden");
}

document.getElementById("finishBtn").addEventListener("click", async () => {
  await autoSaveDraft();
  showFinishModal(false);
});

document.getElementById("cancelFinishBtn").addEventListener("click", () => {
  document.getElementById("finishModal").classList.add("hidden");
});

document.getElementById("confirmFinishBtn").addEventListener("click", async () => {
  await processFinish();
});

async function forceFinishExam() {
  if (autoFinishInProgress) return;
  autoFinishInProgress = true;
  await autoSaveDraft();
  showFinishModal(true);
  await processFinish(true);
}

async function processFinish(autoSubmit = false) {
  const { ok, data } = await fetchJSON(`${sessionApi}/finish`, {
    method: "POST",
    body: JSON.stringify({ auto_submit: autoSubmit }),
  });
  if (!ok || !data.success) {
    await window.showAppAlert(data.message || "Không thể kết thúc phiên làm bài.");
    return;
  }
  if (data.submissions) submissionsData = data.submissions;

  let totalScore = 0;
  const maxScorePerQuestion = exercises.length ? 10 / exercises.length : 0;
  exercises.forEach(ex => {
    const submission = submissionsData[ex.id];
    if (submission && submission.status !== "pending" && submission.max_score > 0) {
      totalScore += (submission.score / submission.max_score) * maxScorePerQuestion;
    }
  });

  clearInterval(timerInterval); // Dừng đồng hồ
  examFinished = true;
  clearInterval(proctoringTimer);
  clearTimeout(focusDebounceTimer);
  document.removeEventListener("visibilitychange", handleExamVisibilityChange);
  window.removeEventListener("blur", scheduleFocusViolation);
  window.removeEventListener("focus", clearFocusViolation);
  window.removeEventListener("pagehide", saveDraftOnPageHide);
  restoreOfficialExamNavigation();

  document.getElementById("finalScore").textContent = Math.min(10, totalScore).toFixed(2);
  document.getElementById("finalMaxScore").textContent = exercises.length ? "10" : "0";
  
  document.getElementById("summaryStep").style.display = "none";
  document.getElementById("scoreStep").style.display = "block";
}

document.getElementById("closeFinishBtn").addEventListener("click", () => {
  window.location.href = returnUrl;
});

// KHỞI ĐỘNG
initEditor();
if (isFreeSession) {
  loadWorkspace();
} else {
  Promise.resolve(window.examResumeReady)
    .then(shouldLoad => {
      if (shouldLoad !== false) return loadWorkspace();
      return null;
    })
    .catch(error => {
      console.error("Không thể chuẩn bị khôi phục bài thi.", error);
      return loadWorkspace();
    });
}