# Documents

**Menu > Documents** keeps files you add so a chat can answer questions about them. You can also tap the **+** next to the message box to attach documents to the chat you are in.

- **Reads:** PDF (with page marks), Word (.docx, tables included), HTML, and text files: .txt, .md, .csv, .json, code and more. Not scans or pictures (the app says so), not the old .doc.
- **Limits:** 10 MB per file, about 1.5 million letters of text per document, 40 documents per person. Problems come back as plain messages.
- **Ask:** In the Documents list, **Ask** starts a new chat with that file attached. The attached files show as chips above the message box (tap x to remove).
- **How the model reads it:** Nothing is trained. A short document goes to the model whole. For a long one the app picks the passages that share the most (rarer) words with your question; for "summarize this" style questions it spreads the passages over the whole document. The model is told to answer from the document, say which page or part when shown, and say so plainly if the answer is not in it. While documents are attached, Wikipedia and web lookups are off for that chat so they don't distract.
- **Privacy:** The files stay on the computer that runs the app, in your own file (`docs-<you>.db`). Other people on the app never see them. They are in "Download my data", and "Delete everything" removes them.
- **Needs:** `pip install pypdf python-docx` (in requirements.txt).
