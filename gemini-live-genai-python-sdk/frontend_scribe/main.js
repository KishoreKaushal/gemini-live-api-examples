// --- Clinical Scribe: Main Application Logic ---

const statusDiv = document.getElementById("status");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const restartBtn = document.getElementById("restartBtn");
const micBtn = document.getElementById("micBtn");
const analyzeBtn = document.getElementById("analyzeBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const connectBtn = document.getElementById("connectBtn");
const chatLog = document.getElementById("chat-log");
const analysisPanel = document.getElementById("analysis-panel");
const analysisResult = document.getElementById("analysis-result");

// Accumulate all transcript fragments for the Brain phase
let fullTranscript = [];
let currentTranscriptDiv = null;

const mediaHandler = new MediaHandler();
const geminiClient = new GeminiClient({
  onOpen: () => {
    statusDiv.textContent = "Connected";
    statusDiv.className = "status connected";
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");
  },
  onMessage: (event) => {
    // In scribe mode, we only receive JSON events (no binary audio)
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        handleJsonMessage(msg);
      } catch (e) {
        console.error("Parse error:", e);
      }
    }
    // Binary data is completely ignored — the model never sends audio back
  },
  onClose: (e) => {
    console.log("WS Closed:", e);
    statusDiv.textContent = "Disconnected";
    statusDiv.className = "status disconnected";
    showSessionEnd();
  },
  onError: (e) => {
    console.error("WS Error:", e);
    statusDiv.textContent = "Connection Error";
    statusDiv.className = "status error";
  },
});

function handleJsonMessage(msg) {
  if (msg.type === "transcript") {
    // Live transcription fragment — append to screen
    if (currentTranscriptDiv) {
      currentTranscriptDiv.textContent += msg.text;
    } else {
      currentTranscriptDiv = appendMessage("transcript", msg.text);
    }
    chatLog.scrollTop = chatLog.scrollHeight;

    // Accumulate for the Brain phase
    fullTranscript.push(msg.text);
  } else if (msg.type === "error") {
    appendMessage("error", "Error: " + msg.error);
  }
}

function appendMessage(type, text) {
  // Remove the initial "Waiting for audio..." system message
  const systemMsg = chatLog.querySelector(".message.system");
  if (systemMsg) systemMsg.remove();

  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${type}`;
  msgDiv.textContent = text;
  chatLog.appendChild(msgDiv);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgDiv;
}

// Connect Button Handler
connectBtn.onclick = async () => {
  statusDiv.textContent = "Connecting...";
  connectBtn.disabled = true;

  try {
    await mediaHandler.initializeAudio();
    geminiClient.connect();
  } catch (error) {
    console.error("Connection error:", error);
    statusDiv.textContent = "Connection Failed: " + error.message;
    statusDiv.className = "status error";
    connectBtn.disabled = false;
  }
};

// Disconnect
disconnectBtn.onclick = () => {
  geminiClient.disconnect();
};

// Mic toggle
micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    micBtn.textContent = "Start Mic";
    micBtn.classList.remove("recording");
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) {
          geminiClient.send(data);
        }
      });
      micBtn.textContent = "⏺ Recording...";
      micBtn.classList.add("recording");
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

// Analyze Button — End session and send to the Brain
analyzeBtn.onclick = async () => {
  const transcript = fullTranscript.join(" ").trim();
  if (!transcript) {
    alert("No transcript to analyze. Speak first!");
    return;
  }

  // Stop recording and disconnect
  mediaHandler.stopAudio();
  micBtn.textContent = "Start Mic";
  micBtn.classList.remove("recording");
  geminiClient.disconnect();

  // Show loading state
  analysisPanel.classList.remove("hidden");
  analysisResult.textContent = "Analyzing transcript...";
  analyzeBtn.disabled = true;

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: transcript }),
    });

    const result = await response.json();

    if (result.status === "ok") {
      analysisResult.textContent = JSON.stringify(result.data, null, 2);
    } else {
      analysisResult.textContent = "Error: " + result.error;
    }
  } catch (e) {
    analysisResult.textContent = "Network error: " + e.message;
  }
};

// Reset / Restart
function resetUI() {
  authSection.classList.remove("hidden");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");
  analysisPanel.classList.add("hidden");

  mediaHandler.stopAudio();
  micBtn.textContent = "Start Mic";
  micBtn.classList.remove("recording");
  chatLog.innerHTML = '<div class="message system" style="color: #888; font-style: italic;">Waiting for audio... Start the mic and begin speaking.</div>';
  connectBtn.disabled = false;
  analyzeBtn.disabled = false;
  fullTranscript = [];
  currentTranscriptDiv = null;
}

function showSessionEnd() {
  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  mediaHandler.stopAudio();
}

restartBtn.onclick = () => {
  resetUI();
};
