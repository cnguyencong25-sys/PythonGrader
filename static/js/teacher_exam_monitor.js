async function fetchMonitorJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

const monitorRows = document.getElementById("monitorRows");
const monitorError = document.getElementById("monitorError");
const monitorUpdatedAt = document.getElementById("monitorUpdatedAt");
let monitorRequestPending = false;
let monitorTimer = null;

const statusLabels = {
  not_started: ["Chưa làm", "not-started"],
  in_progress: ["Đang làm", "in-progress"],
  completed: ["Đã hoàn thành", "completed"],
  cheating: ["Gian lận", "cheating"],
};

function createCell(text, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = text;
  return cell;
}

function renderEventLog(events) {
  const cell = document.createElement("td");
  cell.className = "monitor-event-cell";
  if (!events.length) {
    cell.textContent = "Chưa ghi nhận";
    return cell;
  }

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = `${events.length} mốc thời gian`;
  details.appendChild(summary);
  const list = document.createElement("ul");
  list.className = "monitor-event-list";
  events.forEach(event => {
    const item = document.createElement("li");
    const timestamp = document.createElement("time");
    timestamp.dateTime = event.occurred_at || "";
    timestamp.textContent = event.occurred_at
      ? formatVietnamDateTime(event.occurred_at)
      : "Thời gian không xác định";
    const detail = document.createElement("span");
    detail.textContent = event.detail || event.event_type || "Hành vi bất thường";
    item.append(timestamp, detail);
    list.appendChild(item);
  });
  details.appendChild(list);
  cell.appendChild(details);
  return cell;
}

function renderParticipants(participants) {
  monitorRows.replaceChildren();
  if (!participants.length) {
    const row = document.createElement("tr");
    const cell = createCell("Hệ thống chưa có tài khoản sinh viên.", "monitor-empty");
    cell.colSpan = 6;
    row.appendChild(cell);
    monitorRows.appendChild(row);
    return;
  }

  participants.forEach(participant => {
    const row = document.createElement("tr");
    row.dataset.userId = String(participant.user_id);
    row.appendChild(createCell(participant.student_id || "—"));
    row.appendChild(createCell(participant.full_name || "—"));

    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    const [label, className] = statusLabels[participant.status] || statusLabels.not_started;
    badge.className = `exam-monitor-status ${className}`;
    badge.textContent = label;
    statusCell.appendChild(badge);
    row.appendChild(statusCell);

    row.appendChild(createCell(`${participant.abnormal_count}/5`, "monitor-count"));
    row.appendChild(renderEventLog(participant.events || []));

    const actionCell = document.createElement("td");
    const action = document.createElement("button");
    action.type = "button";
    action.className = participant.is_blocked
      ? "btn-secondary monitor-block-button is-blocked"
      : "btn-warning monitor-block-button";
    action.dataset.userId = String(participant.user_id);
    action.dataset.blocked = participant.is_blocked ? "true" : "false";
    action.textContent = participant.is_blocked ? "Bỏ chặn" : "Chặn bài kiểm tra";
    actionCell.appendChild(action);
    row.appendChild(actionCell);
    monitorRows.appendChild(row);
  });
}

async function loadMonitor() {
  if (monitorRequestPending) return;
  monitorRequestPending = true;
  try {
    const { ok, data } = await fetchMonitorJSON(
      `/api/exams/${window.examMonitorId}/monitor`
    );
    if (!ok || !data.success) {
      monitorError.textContent = data.message || "Không tải được dữ liệu giám sát.";
      return;
    }
    monitorError.textContent = "";
    renderParticipants(data.participants || []);
    monitorUpdatedAt.textContent = `Cập nhật: ${formatVietnamDateTime(data.updated_at)}`;
  } catch (error) {
    monitorError.textContent = "Không kết nối được máy chủ giám sát.";
  } finally {
    monitorRequestPending = false;
  }
}

monitorRows.addEventListener("click", async event => {
  const button = event.target.closest(".monitor-block-button");
  if (!button || button.disabled) return;

  const isBlocked = button.dataset.blocked === "true";
  if (!isBlocked && !window.confirm(
    "Chặn bài thi của sinh viên này Điểm sẽ được chốt 0 cho đến khi bỏ chặn."
  )) return;

  button.disabled = true;
  monitorError.textContent = "";
  try {
    const { ok, data } = await fetchMonitorJSON(
      `/api/exams/${window.examMonitorId}/monitor/students/${button.dataset.userId}/toggle-block`,
      { method: "POST" }
    );
    if (!ok || !data.success) {
      monitorError.textContent = data.message || "Không thể cập nhật trạng thái chặn.";
      button.disabled = false;
      return;
    }
    await loadMonitor();
  } catch (error) {
    monitorError.textContent = "Không kết nối được máy chủ giám sát.";
    button.disabled = false;
  }
});

document.getElementById("refreshMonitor").addEventListener("click", loadMonitor);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) loadMonitor();
});

async function pollMonitor() {
  await loadMonitor();
  monitorTimer = setTimeout(pollMonitor, 3000);
}

pollMonitor();
