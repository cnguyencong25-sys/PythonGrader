async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const wsLayout = document.querySelector(".workspace-layout");
const sessionId = wsLayout.dataset.sessionId;

let exercises = [];
let currentExIndex = -1;
let editor = null;
let submissionsData = {};
let autoSaveTimeout = null;
let timerInterval = null;

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
  await fetchJSON(`/api/student/exam-sessions/${sessionId}/save-draft`, {
    method: "POST", body: JSON.stringify({ exercise_id: ex.id, code: editor.getValue() })
  });
}

// 3. LOAD WORKSPACE & BẮT ĐẦU ĐẾM NGƯỢC
async function loadWorkspace() {
  const { ok, data } = await fetchJSON(`/api/student/exam-sessions/${sessionId}`);
  
  if (!ok || !data.success) {
    alert(data.message || "Lỗi tải dữ liệu hoặc đã hết giờ.");
    window.location.href = "/student/exams";
    return;
  }

  exercises = data.exam.exercises;
  submissionsData = data.submissions || {};

  renderExerciseGrid();
  if (exercises.length > 0) selectExercise(0);

  // Bắt đầu đếm ngược
  startCountdown(data.remain_seconds);
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

  document.querySelectorAll(".ex-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelector(`.ex-btn[data-index="${index}"]`).classList.add("active");

  document.getElementById("problemBody").style.display = "flex";
  document.getElementById("problemTitle").textContent = `Bài ${index + 1}: ${ex.title}`;
  document.getElementById("problemDescription").textContent = ex.description;
  document.getElementById("problemOutputFormat").textContent = ex.output_format || "(Không có)";
  document.getElementById("problemConstraints").textContent = ex.constraints || "(Không có)";
  renderStudentSampleCases(ex);

  if (submissionsData[ex.id] && submissionsData[ex.id].code) {
    editor.setValue(submissionsData[ex.id].code);
    if (submissionsData[ex.id].status !== "pending") updateSubmitResultUI(submissionsData[ex.id]);
    else document.getElementById("submitResult").textContent = "";
  } else {
    editor.setValue("def solve():\n    # Viết code của bạn ở đây\n    pass\n");
    document.getElementById("submitResult").textContent = "";
  }
}

function updateSubmitResultUI(result) {
  const resEl = document.getElementById("submitResult");
  if (result.status === "correct") {
    resEl.textContent = "✅ Đúng hoàn toàn!";
    resEl.className = "submit-result correct";
  } else if (result.status === "partial") {
    resEl.textContent = "⚠️ Đúng một phần.";
    resEl.className = "submit-result partial";
  } else {
    resEl.textContent = "❌ Sai.";
    resEl.className = "submit-result wrong";
  }
}

// 4. NỘP BÀI TỪNG CÂU
document.getElementById("submitBtn").addEventListener("click", async () => {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const btn = document.getElementById("submitBtn");
  btn.disabled = true; btn.textContent = "⏳ Đang chấm...";

  try {
    const { ok, data } = await fetchJSON(`/api/student/exam-sessions/${sessionId}/submit`, {
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
      alert(data.message || "Lỗi nộp bài.");
    }
  } catch (err) {
    alert("Lỗi kết nối máy chủ.");
  } finally {
    btn.disabled = false; btn.textContent = "🚀 Nộp bài";
  }
});

// 5. ĐỒNG HỒ ĐẾM NGƯỢC (QUAN TRỌNG)
function startCountdown(totalSeconds) {
  const timerText = document.getElementById("timeText");
  const timerBox = document.getElementById("timerDisplay");
  let remain = totalSeconds;

  timerInterval = setInterval(() => {
    remain--;
    
    // Format mm:ss
    const m = Math.floor(remain / 60).toString().padStart(2, '0');
    const s = (remain % 60).toString().padStart(2, '0');
    timerText.textContent = `${m}:${s}`;

    // Cảnh báo khi còn < 5 phút
    if (remain <= 300) timerBox.classList.add("warning");

    // Hết giờ -> Tự động nộp
    if (remain <= 0) {
      clearInterval(timerInterval);
      alert("⏰ Đã hết thời gian làm bài! Hệ thống tự động nộp bài.");
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
    const icon = { correct: "✅", partial: "⚠️", wrong: "❌", pending: "⏳" }[status];
    return `<div class="summary-item status-${status}">
        <span>${icon} Bài ${i + 1}: ${ex.title}</span>
        <strong>${statusText}</strong>
      </div>`;
  }).join("");

  if(isAuto) {
    document.getElementById("modalTitle").textContent = "⏰ Đã hết giờ làm bài";
    document.getElementById("cancelFinishBtn").style.display = "none"; // Không cho tiếp tục
  } else {
    document.getElementById("modalTitle").textContent = "🏁 Xác nhận nộp bài";
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
  await autoSaveDraft();
  showFinishModal(true);
  await processFinish(); // Tự động gọi API finish
}

async function processFinish() {
  let totalScore = 0;
  const maxScorePerQuestion = exercises.length ? 10 / exercises.length : 0;
  exercises.forEach(ex => {
    const submission = submissionsData[ex.id];
    if (submission && submission.status !== "pending" && submission.max_score > 0) {
      totalScore += (submission.score / submission.max_score) * maxScorePerQuestion;
    }
  });

  await fetchJSON(`/api/student/exam-sessions/${sessionId}/finish`, { method: "POST" });
  clearInterval(timerInterval); // Dừng đồng hồ

  document.getElementById("finalScore").textContent = Math.min(10, totalScore).toFixed(2);
  document.getElementById("finalMaxScore").textContent = exercises.length ? "10" : "0";
  
  document.getElementById("summaryStep").style.display = "none";
  document.getElementById("scoreStep").style.display = "block";
}

document.getElementById("closeFinishBtn").addEventListener("click", () => {
  window.location.href = "/student/exams";
});

// KHỞI ĐỘNG
initEditor();
loadWorkspace();