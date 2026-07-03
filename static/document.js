const contentEl = document.querySelector("#document-content");

function escapeRawHtml(markdown) {
  return markdown.replace(/</g, "&lt;");
}

function forceMarkdownLineBreaks(markdown) {
  const lines = markdown.split("\n");
  const output = [];

  let inFence = false;
  let fenceMarker = "";

  for (const line of lines) {
    const trimmed = line.trimStart();

    if (
      trimmed.startsWith("```") ||
      trimmed.startsWith("~~~")
    ) {
      const marker = trimmed.slice(0, 3);

      if (!inFence) {
        inFence = true;
        fenceMarker = marker;
      } else if (marker === fenceMarker) {
        inFence = false;
        fenceMarker = "";
      }

      output.push(line);
      continue;
    }

    if (inFence || line.trim() === "") {
      output.push(line);
      continue;
    }

    output.push(`${ line }  `);
  }

  return output.join("\n");
}

function renderMarkdown(markdown) {
  const markdownWithoutRawHtml = escapeRawHtml(markdown);
  const markdownWithHardBreaks = forceMarkdownLineBreaks(
    markdownWithoutRawHtml
  );

  const unsafeHtml = marked.parse(markdownWithHardBreaks, {
    gfm: true,
    breaks: true,
  });

  return DOMPurify.sanitize(unsafeHtml);
}

function renderDocument() {
  if (!contentEl || !window.QUILLQR_DOCUMENT) {
    return;
  }

  const { content, contentFormat } = window.QUILLQR_DOCUMENT;

  if (contentFormat === "markdown") {
    contentEl.innerHTML = renderMarkdown(content);
    contentEl.classList.add("markdown-content");
    return;
  }

  contentEl.textContent = content;
  contentEl.classList.add("plain-text-content");
}

renderDocument();