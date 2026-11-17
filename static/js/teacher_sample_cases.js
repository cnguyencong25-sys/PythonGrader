(() => {
  const list = document.getElementById("sampleCaseList");
  const addButton = document.getElementById("addSampleCase");
  if (!list || !addButton) return;

  function updateLabels() {
    list.querySelectorAll(".sample-case-row").forEach((row, index) => {
      const number = index + 1;
      const labels = row.querySelectorAll(".sample-case-field label");
      const inputs = [
        row.querySelector(".sample-case-input"),
        row.querySelector(".sample-case-output"),
      ];
      labels[0].textContent = `Input mẫu ${number}`;
      labels[1].textContent = `Output mẫu ${number}`;
      labels[0].htmlFor = `sampleInput-${number}`;
      labels[1].htmlFor = `sampleOutput-${number}`;
      inputs[0].id = labels[0].htmlFor;
      inputs[1].id = labels[1].htmlFor;
      row.querySelector(".sample-case-remove")
        .setAttribute("aria-label", `Xóa cặp mẫu ${number}`);
    });
  }

  function addSampleCase() {
    const row = document.createElement("div");
    row.className = "sample-case-row";
    row.innerHTML = `
      <div class="sample-case-field">
        <label></label>
        <textarea class="sample-case-input" rows="3"></textarea>
      </div>
      <div class="sample-case-field">
        <label></label>
        <textarea class="sample-case-output" rows="3"></textarea>
      </div>
      <button type="button" class="btn-secondary sample-case-remove">Xóa</button>
    `;
    list.appendChild(row);
    updateLabels();
    row.querySelector(".sample-case-input").focus();
  }

  addButton.addEventListener("click", addSampleCase);
  list.addEventListener("click", event => {
    const button = event.target.closest(".sample-case-remove");
    if (!button) return;
    button.closest(".sample-case-row").remove();
    updateLabels();
  });

  window.collectSampleExamples = () =>
    Array.from(list.querySelectorAll(".sample-case-row"))
      .map(row => ({
        input: row.querySelector(".sample-case-input").value,
        output: row.querySelector(".sample-case-output").value,
      }))
      .filter(example => example.input.trim() || example.output.trim());

  updateLabels();
})();
