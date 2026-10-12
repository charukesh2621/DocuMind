import { API_BASE } from './api.js';
import { addDocumentToCurrentChat } from './chat.js';

const fileInput = document.getElementById("fileInput");
const uploadStatusEl = document.getElementById("uploadStatus");

export function initDocuments() {
    document.getElementById("addDocsBtn").addEventListener("click", () => {
        fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) {
            uploadFile(fileInput.files[0]);
        }
    });
}

export function showUploadStatus(message, isError) {
    uploadStatusEl.textContent = message;
    uploadStatusEl.className = isError ? "error" : "success";

    setTimeout(() => {
        uploadStatusEl.className = "";
        uploadStatusEl.textContent = "";
    }, 4000);
}

async function uploadFile(file) {
    showUploadStatus(`Uploading ${file.name}...`, false);

    try {
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(API_BASE + "/upload", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Upload failed");
        }

        showUploadStatus("Upload successful. Processing document...", false);

        fileInput.value = "";

        addDocumentToCurrentChat(data.saved_filename);

    } catch (error) {
        console.error("Upload failed:", error);
        showUploadStatus(error.message || "Upload failed", true);
        fileInput.value = "";
    }
}
