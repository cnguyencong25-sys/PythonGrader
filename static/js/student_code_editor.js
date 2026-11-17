function createStudentCodeEditor(textarea, options) {
  const editorAttributes = {
    autocomplete: "off",
    autocorrect: "off",
    autocapitalize: "off",
    spellcheck: "false",
    "aria-autocomplete": "none",
    "data-ms-editor": "false",
    "data-gramm": "false",
  };

  Object.entries(editorAttributes).forEach(([name, value]) => {
    textarea.setAttribute(name, value);
  });

  const editor = CodeMirror.fromTextArea(textarea, {
    spellcheck: false,
    ...options,
  });
  const inputField = editor.getInputField();
  Object.entries(editorAttributes).forEach(([name, value]) => {
    inputField.setAttribute(name, value);
  });
  inputField.setAttribute("role", "textbox");
  inputField.setAttribute("aria-multiline", "true");
  return editor;
}
