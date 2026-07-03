const titleInput = document.querySelector("#title");
const formatInput = document.querySelector("#content-format");
const contentInput = document.querySelector("#content");
const createButton = document.querySelector("#create-button");
const statusEl = document.querySelector("#status");

const resultEl = document.querySelector("#result");
const publicLinkEl = document.querySelector("#public-link");
const editLinkEl = document.querySelector("#edit-link");

const qrCodeEl = document.querySelector("#qr-code");
const downloadQrButton = document.querySelector(
  "#download-qr-button"
);

let latestQrPayload = "";
let latestQrName = "quillqr-document.png";

function setStatus(message) {
  statusEl.textContent = message;
}

function clearQrCode() {
  qrCodeEl.replaceChildren();
  latestQrPayload = "";
}

function makeSafeFilename(value) {
  const cleaned = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  if (!cleaned) {
    return "quillqr-document";
  }

  return cleaned.slice(0, 80);
}

function generateQrCode(payload) {
  clearQrCode();

  latestQrPayload = payload;

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

function getQrImage() {
  return qrCodeEl.querySelector("img");
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

async function createDocument() {
  setStatus("Creating document...");

  resultEl.classList.add("hidden");
  clearQrCode();

  const response = await fetch("/api/documents", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      title: titleInput.value,
      content: contentInput.value,
      content_format: formatInput.value,
    }),
  });

  const data = await response.json();

  if (!response.ok || !data.ok) {
    setStatus(data.error || "Failed to create document.");
    return;
  }

  publicLinkEl.href = data.public_url;
  publicLinkEl.textContent = data.public_url;

  editLinkEl.href = data.edit_url;
  editLinkEl.textContent = data.edit_url;

  latestQrName = `${ makeSafeFilename(
    titleInput.value || data.read_slug
  ) }-qr.png`;

  generateQrCode(data.public_url);

  resultEl.classList.remove("hidden");

  setStatus(
    `Created. Expires at ${ data.expires_at }.`
  );
}

createButton.addEventListener("click", () => {
  createDocument().catch((error) => {
    console.error(error);
    setStatus("Unexpected error.");
  });
});

downloadQrButton.addEventListener("click", () => {
  downloadQrPng();
});
