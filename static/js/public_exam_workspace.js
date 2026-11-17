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
  const submission = submissions[question.id];
  document.getElementById("problemTitle").textContent = `${index + 1}. ${question.title}`;
  document.getElementById("problemDescription").textContent = question.description || "";
  document.getElementById("problemOutputFormat").textContent = question.output_format || "(Không có)";
  document.getElementById("problemConstraints").textContent = question.constraints || "(Không có)";
  renderStudentSampleCases(question);
  document.getElementById("problemBody").hidden = false;
  document.getElementById("submitResult").textContent = submission && submission.status !== "pending"
    ? gradingStatusLabel(submission.status) : "";
  editor.setValue(submission ? submission.code : "def solve():\n    pass\n");
  editor.setOption("readOnly", readOnly);
}

function gradingStatusLabel(status) {
  const labels = {
    correct: "✅ Đúng hoàn toàn!",
    partial: "⚠️ Đúng một phần.",
    wrong: "❌ Sai.",
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
  if (readOnly || focusLost) return;
  focusLost = true;
  window.alert("Cảnh báo: hệ thống đã ghi nhận bạn rời khỏi màn hình thi.");
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
document.getElementById("finishBtn").addEventListener("click", () => {
  if (window.confirm("Bạn chắc chắn muốn kết thúc và nộp bài?")) finishExam();
});

setupEditor();
loadWorkspace();
