const studentLayout = document.querySelector(".student-layout.has-workspace-taskbar");
if (studentLayout) {
  const collapseButton = studentLayout.querySelector(".student-taskbar-collapse");
  const reopenButton = studentLayout.querySelector(".student-taskbar-reopen");

  if (collapseButton && reopenButton) {
    const setCollapsed = collapsed => {
      studentLayout.classList.toggle("taskbar-collapsed", collapsed);
      collapseButton.hidden = collapsed;
      collapseButton.setAttribute("aria-expanded", String(!collapsed));
      reopenButton.hidden = !collapsed;
      reopenButton.setAttribute("aria-expanded", String(collapsed));
    };

    collapseButton.addEventListener("click", () => setCollapsed(true));
    reopenButton.addEventListener("click", () => setCollapsed(false));
  }
}
