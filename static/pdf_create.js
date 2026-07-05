const fileInput = document.querySelector("#pdf-file");
const uploadButton = document.querySelector("#upload-button");
const statusEl = document.querySelector("#status");

const resultEl = document.querySelector("#result");
const publicLinkEl = document.querySelector("#public-link");
const editLinkEl = document.querySelector("#edit-link");

const qrCodeEl = document.querySelector("#qr-code");
const downloadQrButton = document.querySelector(
  "#download-qr-button"
);

const maxPdfBytes = Number(window.QUILLQR_MAX_PDF_BYTES) || 0;

let latestQrName = "quillqr-pdf-qr.png";

function setStatus(message) {
  statusEl.textContent = message;
}

function clearQrCode() {
  qrCodeEl.replaceChildren();
}

function makeSafeFilename(value) {
  const cleaned = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  if (!cleaned) {
    return "quillqr-pdf";
  }

  return cleaned.slice(0, 80);
}

function generateQrCode(payload) {
  clearQrCode();

  new QRCode(qrCodeEl, {
    text: payload,
    width: 256,
    height: 256,
    colorDark: "#000000",
    colorLight: "#ffffff",
    correctLevel: QRCode.CorrectLevel.M,
  });
}

function getQrCanvas() {
  return qrCodeEl.querySelector("canvas");
}

function downloadQrPng() {
  const canvas = getQrCanvas();

  if (!canvas) {
    setStatus("No QR code is available to download.");
    return;
  }

  const quietZone = 48;

  const exportCanvas = document.createElement("canvas");
  exportCanvas.width = canvas.width + quietZone * 2;
  exportCanvas.height = canvas.height + quietZone * 2;

  const context = exportCanvas.getContext("2d");

  context.fillStyle = "#ffffff";
  context.fillRect(
    0,
    0,
    exportCanvas.width,
    exportCanvas.height
  );

  context.drawImage(
    canvas,
    quietZone,
    quietZone
  );

  const link = document.createElement("a");
  link.href = exportCanvas.toDataURL("image/png");
  link.download = latestQrName;
  link.click();
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
    setStatus("Choose a PDF file first.");
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

async function createPdfDocument() {
  const file = await getSelectedPdfFile();

  if (!file) {
    return;
  }

  setStatus("Uploading and checking PDF...");
  resultEl.classList.add("hidden");
  clearQrCode();

  const formData = new FormData();
  formData.append("pdf", file);

  const response = await fetch(window.location.pathname, {
    method: "POST",
    body: formData,
  });

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

  publicLinkEl.href = data.public_url;
  publicLinkEl.textContent = data.public_url;

  editLinkEl.href = data.edit_url;
  editLinkEl.textContent = data.edit_url;

  latestQrName = `${ makeSafeFilename(
    file.name.replace(/\.pdf$/i, "") || data.read_slug
  ) }-qr.png`;

  generateQrCode(data.public_url);

  resultEl.classList.remove("hidden");

  setStatus(
    `Uploaded. Pages: ${ data.page_count }. Text pages: ${ data.text_page_count } (${ Math.round(data.text_page_percent) }%). Expires at ${ data.expires_at }.`
  );
}

uploadButton.addEventListener("click", () => {
  createPdfDocument().catch((error) => {
    console.error(error);
    setStatus("Unexpected error.");
  });
});

downloadQrButton.addEventListener("click", () => {
  downloadQrPng();
});
