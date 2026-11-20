const studentThemeStorageKey = "pythonGraderStudentTheme";

function getStudentTheme() {
  try {
    return localStorage.getItem(studentThemeStorageKey) === "dark" ? "dark" : "light";
  } catch (error) {
    console.warn("Không thể đọc tùy chọn giao diện đã lưu.", error);
    return "light";
  }
}

function setStudentTheme(theme, savePreference = false) {
  document.documentElement.dataset.studentTheme = theme;
  document.querySelectorAll("[data-theme-toggle]").forEach(toggle => {
    const isDark = theme === "dark";
    toggle.setAttribute("aria-pressed", String(isDark));
    toggle.setAttribute(
      "aria-label",
      isDark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"
    );
    toggle.querySelector(".student-theme-icon").textContent = "";
    toggle.querySelector(".student-theme-label").textContent =
      isDark ? "Chế độ sáng" : "Chế độ tối";
  });

  if (!savePreference) return;
  try {
    localStorage.setItem(studentThemeStorageKey, theme);
  } catch (error) {
    console.warn("Không thể lưu tùy chọn giao diện.", error);
  }
}

setStudentTheme(getStudentTheme());
document.addEventListener("DOMContentLoaded", () => {
  setStudentTheme(document.documentElement.dataset.studentTheme || "light");
  document.querySelectorAll("[data-theme-toggle]").forEach(toggle => {
    toggle.addEventListener("click", () => {
      const nextTheme =
        document.documentElement.dataset.studentTheme === "dark" ? "light" : "dark";
      setStudentTheme(nextTheme, true);
    });
  });
});
