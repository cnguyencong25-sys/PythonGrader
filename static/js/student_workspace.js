async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const wsLayout = document.querySelector(".workspace-layout");
const chapterId = wsLayout.dataset.chapterId;
const sessionId = wsLayout.dataset.sessionId; // Lấy session ID

let exercises = [];
let currentExIndex = -1;
let editor = null;
let submissionsData = {};
let autoSaveTimeout = null;
let runInputs = [];
let previousRunOutput = "";
let runTranscript = "";
let runGeneration = 0;

// Khởi tạo CodeMirror
function initEditor() {
  editor = createStudentCodeEditor(document.getElementById("codeEditor"), {
    mode: "python",
    theme: "dracula",
    lineNumbers: false,
    autoCloseBrackets: true,
    indentUnit: 4,
    tabSize: 4,
  });
  editor.setSize("100%", "100%");

  // Bắt sự kiện gõ phím -> Tự động lưu nháp (Debounce 1.5s)
  editor.on("change", () => {
    if (currentExIndex === -1) return;
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(() => autoSaveDraft(), 1500);
  });
}

// Lưu nháp ngầm (không chấm điểm)
async function autoSaveDraft() {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const code = editor.getValue();
  
  await fetchJSON(`/api/student/sessions/${sessionId}/save-draft`, {
    method: "POST",
    body: JSON.stringify({ exercise_id: ex.id, code })
  });
  console.log("Auto-saved draft for ex", ex.id);
}

// Load dữ liệu phiên làm bài
async function loadWorkspace() {
  const { ok, data } = await fetchJSON(`/api/student/sessions/${sessionId}`);
  if (!ok || !data.success) {
    await window.showAppAlert(data.message || "Lỗi tải dữ liệu.");
    return;
  }

  exercises = data.chapter.exercises;
  submissionsData = data.submissions || {};

  renderExerciseGrid();

  if (exercises.length > 0) {
    selectExercise(0);
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
      // Trước khi chuyển câu, lưu nháp ngay lập tức (không chờ debounce)
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

  // Load code cũ (từ lúc lưu nháp hoặc nộp bài)
  if (submissionsData[ex.id] && submissionsData[ex.id].code) {
    editor.setValue(submissionsData[ex.id].code);
    if (submissionsData[ex.id].status !== "pending") {
      updateSubmitResultUI(submissionsData[ex.id]);
    } else {
      document.getElementById("submitResult").textContent = "";
    }
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
    const { ok, data } = await fetchJSON(`/api/student/sessions/${sessionId}/run`, {
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

document.getElementById("submitBtn").addEventListener("click", async () => {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const code = editor.getValue();
  const btn = document.getElementById("submitBtn");
  
  btn.disabled = true;
  btn.textContent = "Đang chấm...";

  try {
    const { ok, data } = await fetchJSON(`/api/student/sessions/${sessionId}/submit`, {
      method: "POST",
      body: JSON.stringify({ exercise_id: ex.id, code })
    });

    if (ok && data.success) {
      const result = data.result;
      submissionsData[ex.id] = result;
      
      const exBtn = document.querySelector(`.ex-btn[data-index="${currentExIndex}"]`);
      exBtn.classList.remove("correct", "partial", "wrong");
      if(result.status !== "pending") exBtn.classList.add(result.status);

      updateSubmitResultUI(result);
    }
  } catch (err) {
    await window.showAppAlert("Lỗi kết nối.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Nộp bài";
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

// ==========================================
// XỬ LÝ KẾT THÚC
// ==========================================
document.getElementById("finishBtn").addEventListener("click", async () => {
  await autoSaveDraft(); // Lưu nốt bài đang gõ

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
    return `
      <div class="summary-item status-${status}">
        <span>Bài ${i + 1}: ${ex.title}</span>
        <strong>${statusText}</strong>
      </div>
    `;
  }).join("");

  document.getElementById("summaryStep").style.display = "block";
  document.getElementById("scoreStep").style.display = "none";
  document.getElementById("finishModal").classList.remove("hidden");
});

document.getElementById("confirmFinishBtn").addEventListener("click", async () => {
  let totalScore = 0;
  const maxScorePerQuestion = exercises.length ? 10 / exercises.length : 0;
  
  exercises.forEach(ex => {
    const submission = submissionsData[ex.id];
    if (submission && submission.status !== "pending" && submission.max_score > 0) {
      totalScore += (submission.score / submission.max_score) * maxScorePerQuestion;
    }
  });

  // Gọi API đánh dấu kết thúc
  await fetchJSON(`/api/student/sessions/${sessionId}/finish`, { method: "POST" });

  document.getElementById("finalScore").textContent = Math.min(10, totalScore).toFixed(2);
  document.getElementById("finalMaxScore").textContent = exercises.length ? "10" : "0";
  
  document.getElementById("summaryStep").style.display = "none";
  document.getElementById("scoreStep").style.display = "block";
});

document.getElementById("closeFinishBtn").addEventListener("click", () => {
  window.location.href = "/student/chapters";
});

// Khởi động
initEditor();
loadWorkspace();