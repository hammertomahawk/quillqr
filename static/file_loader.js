(function () {
  const fileInput = document.querySelector("#document-file");
  const fileStatus = document.querySelector("#file-status");
  const fileTitleInput = document.querySelector("#title");
  const fileFormatInput = document.querySelector("#content-format");
  const fileContentInput = document.querySelector("#content");

  const maxContentBytes =
    Number(window.QUILLQR_MAX_CONTENT_BYTES) || 51200;

  const allowedExtensions = new Set([
    ".txt",
    ".md",
    ".markdown",
  ]);

  function setFileStatus(message) {
    if (fileStatus) {
      fileStatus.textContent = message;
    }
  }

  function getExtension(filename) {
    const index = filename.lastIndexOf(".");

    if (index === -1) {
      return "";
    }

    return filename.slice(index).toLowerCase();
  }

  function inferFormat(filename) {
    const extension = getExtension(filename);

    if (
      extension === ".md" ||
      extension === ".markdown"
    ) {
      return "markdown";
    }

    return "text";
  }

  function titleFromFilename(filename) {
    return filename
      .replace(/\.[^.]+$/, "")
      .replace(/[-_]+/g, " ")
      .trim();
  }

  function getUtf8ByteLength(value) {
    return new TextEncoder().encode(value).length;
  }

  function dispatchFieldEvents() {
    if (fileContentInput) {
      fileContentInput.dispatchEvent(
        new Event("input", { bubbles: true })
      );
    }

    if (fileFormatInput) {
      fileFormatInput.dispatchEvent(
        new Event("change", { bubbles: true })
      );
    }
  }

  async function loadSelectedFile() {
    if (!fileInput || !fileContentInput) {
      return;
    }

    const file = fileInput.files && fileInput.files[0];

    if (!file) {
      setFileStatus("");
      return;
    }

    const extension = getExtension(file.name);

    if (!allowedExtensions.has(extension)) {
      setFileStatus(
        "Unsupported file type. Choose a .txt, .md, or .markdown file."
      );
      fileInput.value = "";
      return;
    }

    if (file.size > maxContentBytes) {
      setFileStatus(
        `File is too large. ${ file.size } bytes selected; max is ${ maxContentBytes } bytes.`
      );
      fileInput.value = "";
      return;
    }

    const text = await file.text();
    const textBytes = getUtf8ByteLength(text);

    if (textBytes > maxContentBytes) {
      setFileStatus(
        `File text is too large after reading. ${ textBytes } bytes; max is ${ maxContentBytes } bytes.`
      );
      fileInput.value = "";
      return;
    }

    fileContentInput.value = text;

    if (fileFormatInput) {
      fileFormatInput.value = inferFormat(file.name);
    }

    if (fileTitleInput && !fileTitleInput.value.trim()) {
      fileTitleInput.value = titleFromFilename(file.name);
    }

    dispatchFieldEvents();

    setFileStatus(
      `Loaded ${ file.name } (${ textBytes } bytes).`
    );
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      loadSelectedFile().catch((error) => {
        console.error(error);
        setFileStatus("Could not load file.");
      });
    });
  }
})();