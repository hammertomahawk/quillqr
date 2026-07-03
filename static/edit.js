const titleInput = document.querySelector("#title");
const formatInput = document.querySelector("#content-format");
const contentInput = document.querySelector("#content");
const saveButton = document.querySelector("#save-button");
const statusEl = document.querySelector("#status");

function setStatus(message) {
  statusEl.textContent = message;
}

async function saveDocument() {
  setStatus("Saving document...");

  const response = await fetch(
    `/api/edit/${ encodeURIComponent(
      window.QUILLQR_EDIT_TOKEN
    ) }`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title: titleInput.value,
        content: contentInput.value,
        content_format: formatInput.value,
      }),
    }
  );

  const data = await response.json();

  if (!response.ok || !data.ok) {
    setStatus(data.error || "Failed to save document.");
    return;
  }

  setStatus(
    `Saved. Renewed until ${ data.expires_at }.`
  );
}

saveButton.addEventListener("click", () => {
  saveDocument().catch((error) => {
    console.error(error);
    setStatus("Unexpected error.");
  });
});