import { initEvidence } from './evidence.js';
import { initDocuments } from './documents.js';
import { initChat, renderAll } from './chat.js';

document.addEventListener('DOMContentLoaded', () => {
    initChat();
    renderAll();
    initEvidence();
    initDocuments();
});
