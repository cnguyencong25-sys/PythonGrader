async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Exam-Session-Token": sessionToken,
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

const layout = document.querySelector(".public-workspace");
const sessionId = layout.dataset.sessionId;
const sessionToken = sessionStorage.getItem(`public-exam-token-${sessionId}`);
const apiBase = `/api/public-exams/sessions/${sessionId}`;
let questions = [];
let currentIndex = -1;
let submissions = {};
let editor;
let saveTimeout;
let countdown;
let readOnly = false;
let focusLost = false;
let antiCheatEnabled = false;
let runInputs = [];
let previousRunOutput = "";
let runTranscript = "";
let runGeneration = 0;

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function setupEditor() {
  editor = createStudentCodeEditor(document.getElementById("codeEditor"), {
    mode: "python", theme: "dracula", lineNumbers: false, autoCloseBrackets: true,
    indentUnit: 4, tabSize: 4,
  });
  editor.setSize("100%", "48vh");
  editor.on("change", () => {
    if (readOnly || currentIndex < 0) return;
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(saveDraft, 1000);
  });
}

async function saveDraft() {
  if (readOnly || currentIndex < 0) return;
  const question = questions[currentIndex];
  const { ok, data } = await requestJSON(`${apiBase}/save-draft`, {
    method: "POST",
    body: JSON.stringify({ question_id: question.id, code: editor.getValue() }),
  });
  if (!ok) document.getElementById("workspaceMessage").textContent = data.message || "Không lưu được bản nháp.";
}

function renderGrid() {
  const grid = document.getElementById("exerciseGrid");
  grid.innerHTML = questions.map((question, index) => {
    const state = submissions[question.id];
    return `<button class="question-button ${escapeHtml(state ? state.status : "")}" data-index="${index}">${index + 1}</button>`;
  }).join("");
  grid.querySelectorAll("button").forEach(button => button.addEventListener("click", async () => {
    await saveDraft();
    showQuestion(Number(button.dataset.index));
  }));
}

function showQuestion(index) {
  if (index < 0 || index >= questions.length) return;
  currentIndex = index;
  const question = questions[index];
  document.getElementById("nextQuestionBtn").disabled = index >= questions.length - 1;
  const submission = submissions[question.id];
  document.getElementById("problemTitle").textContent = `${index + 1}. ${question.title}`;
  document.getElementById("problemDescription").textContent = question.description || "";
  document.getElementById("problemOutputFormat").textContent = question.output_format || "(Không có)";
  document.getElementById("problemConstraints").textContent = question.constraints || "(Không có)";
  renderStudentSampleCases(question);
  document.getElementById("problemBody").hidden = false;
  resetRunPanel();
  document.getElementById("submitResult").textContent = submission && submission.status !== "pending"
    ? gradingStatusLabel(submission.status) : "";
  editor.setValue(submission ? submission.code : "");
  editor.setOption("readOnly", readOnly);
  document.getElementById("runInput").disabled = readOnly;
  document.getElementById("runCodeBtn").disabled = readOnly;
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
  document.getElementById("runCodeBtn").disabled = readOnly;
  document.getElementById("runCodeBtn").textContent = "Chạy thử";
  document.getElementById("runOutput").textContent = "";
  document.getElementById("runStatus").textContent = "";
}

async function executeCurrentCode() {
  if (readOnly || currentIndex < 0) return;
  const generation = runGeneration;
  const question = questions[currentIndex];
  const button = document.getElementById("runCodeBtn");
  const output = document.getElementById("runOutput");
  const status = document.getElementById("runStatus");
  const inputForm = document.getElementById("runInputForm");
  const inputField = document.getElementById("runInput");
  button.disabled = true;
  button.textContent = "Đang chạy...";

  try {
    const { ok, data } = await requestJSON(`${apiBase}/run`, {
      method: "POST",
      body: JSON.stringify({
        question_id: question.id,
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
      button.disabled = readOnly;
      button.textContent = "Chạy thử";
    }
  }
}

async function runCurrentCode() {
  if (readOnly || currentIndex < 0) return;
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
  if (readOnly) return;
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

function gradingStatusLabel(status) {
  const labels = {
    correct: "Đúng hoàn toàn",
    partial: "Đúng một phần",
    wrong: "Sai",
    pending: "",
  };
  return labels[status] || "Chưa có kết quả.";
}

function displayResult(result) {
  document.getElementById("workspaceMessage").textContent =
    `Đã nộp bài. Điểm: ${result.total_score} / ${result.total_max}.`;
}

async function submitQuestion() {
  if (readOnly || currentIndex < 0) return;
  const question = questions[currentIndex];
  const { ok, data } = await requestJSON(`${apiBase}/submit`, {
    method: "POST",
    body: JSON.stringify({ question_id: question.id, code: editor.getValue() }),
  });
  if (!ok || !data.success) {
    document.getElementById("workspaceMessage").textContent = data.message || "Nộp bài thất bại.";
    return;
  }
  submissions[question.id] = data.result;
  document.getElementById("submitResult").textContent = gradingStatusLabel(data.result.status);
  renderGrid();
}

async function finishExam() {
  if (!readOnly) await saveDraft();
  const { ok, data } = await requestJSON(`${apiBase}/finish`, { method: "POST" });
  if (!ok || !data.success) {
    document.getElementById("workspaceMessage").textContent = data.message || "Không thể nộp bài.";
    return;
  }
  readOnly = true;
  submissions = data.submissions || submissions;
  document.getElementById("finishBtn").hidden = true;
  document.getElementById("submitBtn").hidden = true;
  document.getElementById("readonlyBanner").hidden = false;
  if (countdown) clearInterval(countdown);
  if (currentIndex >= 0) showQuestion(currentIndex);
  renderGrid();
  displayResult(data.result);
}

function startCountdown(seconds) {
  let remain = seconds;
  const label = document.getElementById("timeText");
  const tick = () => {
    const safeRemain = Math.max(0, remain);
    label.textContent = `${String(Math.floor(safeRemain / 60)).padStart(2, "0")}:${String(safeRemain % 60).padStart(2, "0")}`;
    if (remain <= 0) {
      clearInterval(countdown);
      finishExam();
    }
    remain -= 1;
  };
  tick();
  countdown = setInterval(tick, 1000);
}

async function loadWorkspace() {
  if (!sessionToken) {
    document.getElementById("workspaceMessage").textContent = "Phiên trình duyệt không còn thông tin xác thực. Hãy quay lại link thi và xác thực lại.";
    return;
  }
  const { ok, data } = await requestJSON(apiBase);
  if (!ok || !data.success) {
    document.getElementById("workspaceMessage").textContent = data.message || "Không tải được bài thi.";
    return;
  }
  questions = data.exam.exercises || [];
  submissions = data.submissions || {};
  antiCheatEnabled = Boolean(data.exam.anti_cheat_enabled);
  readOnly = data.read_only;
  if (readOnly) {
    document.getElementById("finishBtn").hidden = true;
    document.getElementById("submitBtn").hidden = true;
    document.getElementById("readonlyBanner").hidden = false;
    displayResult(data.result);
  }
  renderGrid();
  if (questions.length) showQuestion(0);
  if (!readOnly) startCountdown(data.remain_seconds);
}

async function recordViolation() {
  if (!antiCheatEnabled || readOnly || focusLost) return;
  focusLost = true;
  await window.showAppAlert("Cảnh báo: hệ thống đã ghi nhận bạn rời khỏi màn hình thi.");
  const { ok, data } = await requestJSON(`${apiBase}/violation`, { method: "POST" });
  if (!ok) document.getElementById("workspaceMessage").textContent = data.message || "Không ghi nhận được vi phạm.";
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) recordViolation();
  else focusLost = false;
});
window.addEventListener("blur", recordViolation);
window.addEventListener("focus", () => { focusLost = false; });
document.getElementById("submitBtn").addEventListener("click", submitQuestion);
document.getElementById("nextQuestionBtn").addEventListener("click", async () => {
  if (currentIndex < 0 || currentIndex >= questions.length - 1) return;
  const nextIndex = currentIndex + 1;
  const button = document.getElementById("nextQuestionBtn");
  button.disabled = true;
  clearTimeout(saveTimeout);
  try {
    await saveDraft();
    showQuestion(nextIndex);
  } catch (error) {
    document.getElementById("workspaceMessage").textContent =
      "Không lưu được bản nháp. Vui lòng thử lại.";
  } finally {
    button.disabled = currentIndex < 0 || currentIndex >= questions.length - 1;
  }
});
document.getElementById("runCodeBtn").addEventListener("click", runCurrentCode);
document.getElementById("clearRunOutputBtn").addEventListener("click", clearRunConsole);
document.getElementById("finishBtn").addEventListener("click", () => {
  if (window.confirm("Bạn chắc chắn muốn kết thúc và nộp bài?")) finishExam();
});

setupEditor();
loadWorkspace();
