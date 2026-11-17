function renderStudentSampleCases(question) {
  const container = document.getElementById("problemSampleCases");
  if (!container) return;

  const examples = Array.isArray(question.sample_examples) && question.sample_examples.length
    ? question.sample_examples
    : [{
      input: question.sample_input || "",
      output: question.sample_output || "",
    }];
  const hasSamples = examples.some(example => example.input || example.output);
  const visibleExamples = hasSamples
    ? examples
    : [{ input: "(Không có)", output: "(Không có)" }];

  container.replaceChildren();
  visibleExamples.forEach((example, index) => {
    const pair = document.createElement("section");
    pair.className = "sample-case-pair";

    [["Input", example.input], ["Output", example.output]].forEach(([kind, value]) => {
      const field = document.createElement("div");
      field.className = "sample-case-display-field";
      const heading = document.createElement("h4");
      heading.textContent = `${kind} mẫu ${index + 1}`;
      const content = document.createElement("pre");
      content.textContent = value || "(Trống)";
      field.append(heading, content);
      pair.appendChild(field);
    });

    container.appendChild(pair);
  });
}
