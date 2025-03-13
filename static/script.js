document.addEventListener("DOMContentLoaded", () => {
    const API_BASE_URL = "http://127.0.0.1:8000";
    let uploadedFileName = "";

    // Cache DOM elements
    const elements = {
        fileInput: document.getElementById("fileInput"),
        uploadBtn: document.getElementById("uploadBtn"),
        generateSummaryBtn: document.getElementById("generateSummaryBtn"),
        sendBtn: document.getElementById("sendBtn"),
        questionInput: document.getElementById("questionInput"),
        responseOutput: document.getElementById("responseOutput"),
        uploadStatus: document.getElementById("uploadStatus"),
        chatbox: document.getElementById("chatbox"),
    };

    // Debugging: Check if elements exist
    Object.entries(elements).forEach(([key, element]) => {
        if (!element) console.error(`❌ Error: Element '${key}' not found.`);
    });

    // Attach event listeners safely
    elements.uploadBtn?.addEventListener("click", uploadFile);
    elements.generateSummaryBtn?.addEventListener("click", generateSummary);
    elements.sendBtn?.addEventListener("click", askQuestion);
    elements.questionInput?.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            askQuestion();
        }
    });

    /** Upload File */
    async function uploadFile() {
        console.log("📂 Upload button clicked.");
        const file = elements.fileInput?.files[0];
        if (!file) return alert("Please select a PDF file.");

        uploadedFileName = file.name;
        updateStatus("📤 Uploading...", true);

        const formData = new FormData();
        formData.append("file", file);
        elements.generateSummaryBtn.disabled = true;

        try {
            const response = await fetch(`${API_BASE_URL}/upload/`, {
                method: "POST",
                body: formData,
            });
            if (!response.ok) throw new Error("Upload failed.");

            updateStatus("✅ Upload successful! Click 'Generate Summary'.");
            elements.generateSummaryBtn.disabled = false;
        } catch (error) {
            handleError(error, "Upload failed!");
        }
    }

    /** Generate Summary */
    async function generateSummary() {
        console.log("📑 Generate Summary button clicked.");
        if (!uploadedFileName) return alert("No file uploaded yet!");

        updateStatus("📝 Generating structured notes...", true);
        const fileName = `uploads/${uploadedFileName}`;

        try {
            const response = await fetch(`${API_BASE_URL}/summary/?file_path=${encodeURIComponent(uploadedFileName)}`);
            if (!response.ok || !response.body) throw new Error("Summary generation failed.");

            await streamResponse(response.body);
            updateStatus("✅ Summary completed.");
        } catch (error) {
            handleError(error, "Summary generation failed!");
        }
    }

    /** Ask Question */
    async function askQuestion() {
        console.log("💬 Ask Question button clicked.");
        const query = elements.questionInput?.value.trim();
        if (!query) return alert("Please enter a question.");
    
        // Append user's question to the chatbox
        appendMessage("user", query);
    
        // Clear input field after sending
        elements.questionInput.value = "";
        elements.questionInput.focus();
    
        // Show "Thinking..." message
        const thinkingMessage = appendMessage("bot", "Thinking...", false);
    
        try {
            const response = await fetch(`${API_BASE_URL}/ask/`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({ query }),
            });
    
            const result = await response.json();
            
            // Replace "Thinking..." with the actual response
            appendMessage("bot", result.answer || "No response received.", true);
        } catch (error) {
            appendMessage("bot", "❌ Failed to get a response!", true);
            handleError(error, "Failed to get a response!");
        }
    }
    
    

    /** Stream Response */
    async function streamResponse(body) {
        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const messageDiv = appendMessage("bot", "", true);

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const chunks = buffer.split("\n");
                buffer = chunks.pop();

                for (const chunk of chunks) {
                    if (chunk.trim()) {
                        messageDiv.innerHTML += `<p>${chunk}</p>`;
                        await delay(50);
                    }
                }
            }

            if (buffer.trim()) messageDiv.innerHTML += `<p>${buffer}</p>`;
        } catch (error) {
            handleError(error, "Error streaming response.", messageDiv);
        }
    }

    /** Append Message */
    function appendMessage(sender, text = "", replaceLast = false) {
        const lastMessage = elements.chatbox?.lastElementChild;

        if (replaceLast && lastMessage?.classList.contains(sender)) {
            lastMessage.innerHTML = text;
            return lastMessage;
        }

        const messageDiv = document.createElement("div");
        messageDiv.className = `message ${sender}`;
        messageDiv.innerHTML = text;
        elements.chatbox?.appendChild(messageDiv);
        elements.chatbox.scrollTop = elements.chatbox.scrollHeight;

        return messageDiv;
    }

    /** Update Status */
    function updateStatus(msg, isLoading = false) {
        elements.uploadStatus.innerText = msg;
        elements.uploadStatus.style.color = isLoading ? "blue" : "black";
    }

    /** Delay */
    function delay(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    /** Handle Errors */
    function handleError(error, statusMsg, messageDiv = null) {
        console.error("❌ Error:", error);
        updateStatus(`❌ ${statusMsg}`);
        if (messageDiv) {
            messageDiv.innerHTML = "<b>Error processing document.</b>";
        } else {
            appendMessage("bot", "<b>Error processing document.</b>");
        }
    }
});
