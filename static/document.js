const contentEl = document.querySelector("#document-content");

function escapeRawHtml(markdown) {
  return markdown
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderDocument() {
  if (!contentEl || !window.QUILLQR_DOCUMENT) {
    return;
  }

  const { content, contentFormat } = window.QUILLQR_DOCUMENT;

  if (contentFormat === "markdown") {
    const markdownWithoutRawHtml = escapeRawHtml(content);
    const unsafeHtml = marked.parse(markdownWithoutRawHtml);
    const safeHtml = DOMPurify.sanitize(unsafeHtml);

    contentEl.innerHTML = safeHtml;
    contentEl.classList.add("markdown-content");
    return;
  }

  contentEl.textContent = content;
  contentEl.classList.add("plain-text-content");
}

renderDocument();