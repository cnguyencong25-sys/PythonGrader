function showMsg(el, text, type = "error") {
  if (!el) return;
  el.textContent = text;
  el.className = "message " + type;
}

async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const messageEl = document.getElementById("message");
const form = document.getElementById("exerciseForm");
const chapterId = form.dataset.chapterId;
const exerciseId = form.dataset.exerciseId || null;

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  showMsg(messageEl, "Đang lưu...", "");

  const payload = {
    title: document.getElementById("exTitle").value.trim(),
    description: document.getElementById("exDescription").value.trim(),
    input_format: document.getElementById("exInputFormat").value,
    output_format: document.getElementById("exOutputFormat").value,
    constraints: document.getElementById("exConstraints").value,
    sample_examples: window.collectSampleExamples(),
    generator_code: document.getElementById("exGeneratorCode").value,
    solution_code: document.getElementById("exSolutionCode").value,
    num_test_cases: parseInt(document.getElementById("exNumTests").value) || 10,
  };

  try {
    let res;
    if (exerciseId) {
      res = await fetchJSON(`/api/chapters/exercises/${exerciseId}`, {
        method: "PUT", body: JSON.stringify(payload),
      });
    } else {
      res = await fetchJSON(`/api/chapters/${chapterId}/exercises`, {
        method: "POST", body: JSON.stringify(payload),
      });
    }

    if (!res.ok || !res.data.success) {
      showMsg(messageEl, res.data.message || "Không lưu được.");
      btn.disabled = false;
      return;
    }

    showMsg(messageEl, "Đã lưu bài tập thành công!", "success");
    setTimeout(() => {
      window.location.href = `/teacher/chapters/${chapterId}/edit`;
    }, 800);
  } catch (err) {
    showMsg(messageEl, "Lỗi kết nối.");
    btn.disabled = false;
  }
});