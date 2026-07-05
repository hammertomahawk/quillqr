const fileInput = document.querySelector("#pdf-file");
const uploadButton = document.querySelector("#upload-button");
const statusEl = document.querySelector("#status");

const maxPdfBytes = Number(window.QUILLQR_MAX_PDF_BYTES) || 0;

function setStatus(message) {
  statusEl.textContent = message;
}

async function fileLooksLikePdf(file) {
  const bytes = new Uint8Array(await file.slice(0, 5).arrayBuffer());
  const signature = Array.from(bytes)
    .map((value) => String.fromCharCode(value))
    .join("");

  return signature === "%PDF-";
}

async function getSelectedPdfFile() {
  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    setStatus("Choose a replacement PDF first.");
    return null;
  }

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    setStatus("Only .pdf files are supported.");
    return null;
  }

  if (maxPdfBytes && file.size > maxPdfBytes) {
    setStatus(
      `PDF is too large. ${ file.size } bytes selected; max is ${ maxPdfBytes } bytes.`
    );
    return null;
  }

  if (!(await fileLooksLikePdf(file))) {
    setStatus("That file does not look like a PDF.");
    return null;
  }

  return file;
}

async function replacePdfDocument() {
  const file = await getSelectedPdfFile();

  if (!file) {
    return;
  }

  setStatus("Replacing and checking PDF...");

  const formData = new FormData();
  formData.append("pdf", file);

  const response = await fetch(
    `/p/e/${ encodeURIComponent(
      window.QUILLQR_PDF_EDIT_TOKEN
    ) }`,
    {
      method: "POST",
      body: formData,
    }
  );

  const data = await response.json();

  if (!response.ok || !data.ok) {
    let message = data.error || "Failed to process PDF.";

    if (
      data.text_page_percent !== undefined &&
      data.required_text_page_percent !== undefined
    ) {
      message += ` (${ Math.round(data.text_page_percent) }% text-page coverage; ${ data.required_text_page_percent }% required).`;
    }

    setStatus(message);
    return;
  }

  setStatus(
    `Replaced. Pages: ${ data.page_count }. Text pages: ${ data.text_page_count } (${ Math.round(data.text_page_percent) }%). Renewed until ${ data.expires_at }.`
  );
}

uploadButton.addEventListener("click", () => {
  replacePdfDocument().catch((error) => {
    console.error(error);
    setStatus("Unexpected error.");
  });
});
