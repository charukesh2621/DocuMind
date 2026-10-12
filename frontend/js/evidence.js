export function openEvidenceModal(source) {
    const overlay = document.getElementById("modalOverlay");
    const title = document.getElementById("modalTitle");
    const meta = document.getElementById("modalMeta");
    const text = document.getElementById("modalText");

    title.textContent = source.filename;
    meta.textContent = `Page: ${source.page_number || 'N/A'} | Chunk: ${source.chunk_index || 'N/A'}`;
    text.textContent = source.text || "No supporting text available.";

    overlay.style.display = "flex";
}

export function closeEvidenceModal() {
    document.getElementById("modalOverlay").style.display = "none";
}

export function initEvidence() {
    document.getElementById("modalClose").addEventListener("click", closeEvidenceModal);
    document.getElementById("modalOverlay").addEventListener("click", (e) => {
        if (e.target === document.getElementById("modalOverlay")) closeEvidenceModal();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeEvidenceModal();
    });
}
