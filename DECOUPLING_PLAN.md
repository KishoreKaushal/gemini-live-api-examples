# Mute Scribe Decoupling & Integration Plan

This document outlines the strategy for decoupling the Mute Scribe frontend and backend, enabling Firebase Storage support, and integrating it into the main EHR platform.

---

## 1. Architecture Overview

### Current Architecture (Coupled)
- **Backend (`main_scribe.py`)**: Acts as both the API server and the static file server for the frontend.
- **Frontend (`frontend_scribe/`)**: Relies on `window.location.host` to establish WebSocket connections and make API calls.

### Proposed Architecture (Decoupled)
- **Frontend VM (Static Host)**: Serves `index.html`, `js`, and `css`. Communicates with the backend via public IP/Domain.
- **Backend VM (API/WebSocket Server)**: Handles Gemini Live sessions and transcript analysis.

---

## 2. Incremental Implementation Steps

### Phase 1: Backend Decoupling (Scribe API)
**Goal**: Transform `main_scribe.py` into a standalone, headless API server.
**Tech Stack**: Python 3.10+, FastAPI, Uvicorn, Gemini GenAI SDK.

1.  **Remove Static Serving**: Delete `app.mount("/static", ...)` and the root `@app.get("/")` route from `main_scribe.py`.
2.  **Configure CORS**: Update `CORSMiddleware` to allow the specific origin of your Frontend VM/Domain instead of `["*"]` for production security.
3.  **External Accessibility**: Update `uvicorn.run(host="0.0.0.0")` to allow connections from the public network.
4.  **Environment Sync**: Ensure `GEMINI_API_KEY` and `MODEL` are set via a `.env` file on the VM.

### Phase 2: Frontend Decoupling & Configuration
**Goal**: Allow the frontend to communicate with a remote backend.
**Tech Stack**: Vanilla JavaScript (ES6+), HTML5, CSS3.

1.  **Global Configuration**: Create a `config.js` to store the backend endpoint:
    ```javascript
    const CONFIG = {
        SCRIBE_BACKEND_URL: "http://<BACKEND_VM_IP>:8000",
        EHR_BACKEND_URL: "https://your-ehr-api.com" // For Firebase Storage
    };
    ```
2.  **Dynamic WebSocket**: Update `gemini-client.js` to derive the WebSocket URL from `CONFIG.SCRIBE_BACKEND_URL`.
3.  **Dynamic API Calls**: Update `main.js` to use `CONFIG.SCRIBE_BACKEND_URL` for the `/api/analyze` POST request.

### Phase 3: Audio Persistence to Firebase Storage
**Goal**: Record the session locally and upload the resulting file to the EHR's Firebase Storage.
**Tech Stack**: Web Audio API, MediaRecorder API (or PCM accumulation), EHR Backend API (`UPLOAD_AUDIO`).

1.  **Local Buffering**: Update `MediaHandler.js` to accumulate the PCM chunks into a single buffer during the recording session.
2.  **WAV Encoding**: Implement a utility to convert the accumulated PCM buffer into a standard `.wav` Blob.
3.  **Base64 Conversion**: Create a helper to convert the `Blob` to a `base64` string.
4.  **Upload Execution**: In `main.js`, inside the `analyzeBtn.onclick` handler:
    -   After stopping the mic, trigger `mediaHandler.getWavBase64()`.
    -   Call the EHR Backend's `/clinic` endpoint with `operation: 'UPLOAD_AUDIO'`.
    -   Payload: `{ appointment_id, patient_id, audio_base64, storage_path: "scribe_recordings/${appointment_id}.wav" }`.

### Phase 4: Production Deployment
1.  **Backend VM**: Run `main_scribe.py` behind a process manager like `pm2` or `systemd`.
2.  **Frontend VM**: Serve the `frontend_scribe/` directory using Nginx or Caddy.

---

## 3. Firebase Storage Implementation Detail

The system will leverage the existing EHR Backend infrastructure to avoid duplicating storage logic.

### Frontend Integration (Scribe)
```javascript
async function saveToFirebase(appointmentId, patientId, audioBase64) {
    const payload = {
        appointment_id: appointmentId,
        patient_id: patientId,
        audio_base64: audioBase64
    };

    const response = await fetch(`${CONFIG.EHR_BACKEND_URL}/clinic`, {
        method: "POST",
        headers: { 
            "Content-Type": "application/json",
            "Authorization": `Bearer ${userToken}` // Pass the doctor's session token
        },
        body: JSON.stringify({
            operation: "UPLOAD_AUDIO",
            payload: payload
        }),
    });
    return await response.json();
}
```

### Backend Logic (Existing `upload_audio.py`)
The existing backend already handles:
1.  Decoding the base64 audio.
2.  Uploading to the `clinicstack-dev.firebasestorage.app` bucket.
3.  Generating a persistent download token.
4.  Registering the recording in the `audio_recordings` Firestore collection.

---

## 4. EHR App Integration Strategy

To integrate Mute Scribe without breaking existing functionality, follow this "Side-by-Side" approach:

### 1. Unified Authentication
- The Scribe module should not have its own login. It should inherit the authentication token from the main EHR frontend.
- Store the token in `localStorage` or pass it as a URL parameter if using an iframe.

### 2. Entry Point: Appointment Detail Page
- Add a **"Live Scribe Session"** button next to the "Add Note" button in the `AppointmentDetail.vue` (or equivalent).
- Clicking this button opens the Scribe interface in a Modal or a dedicated route `/clinic/scribe/:appointmentId`.

### 3. Data Hand-off
- **Input**: The EHR app passes `appointment_id` and `patient_id` to the Scribe module.
- **Output**: 
    1.  The AI-generated JSON (Diagnosis, Plan, etc.) is returned to the EHR app.
    2.  The EHR app populates the "Chief Complaint" or "Notes" fields with the AI's suggestions.
    3.  The `recording_id` from the Firebase upload is linked to the appointment's medical history.

### 4. Component Isolation
- Keep the Scribe frontend code in its own directory (e.g., `frontend/src/modules/scribe`).
- Use a shared API service (`ClinicAPI.ts`) to ensure both the main app and the Scribe module use the same logic for storage and data retrieval.

---

## 5. Verification Plan
1.  Start the backend on the API VM (Port 8000).
2.  Start the frontend on the Static VM (Port 80).
3.  Verify that the frontend successfully opens a WebSocket to the API VM and receives live transcriptions.
4.  Verify that "End & Analyze" triggers a WAV conversion and successfully posts to the EHR Backend's `UPLOAD_AUDIO` endpoint.
5.  Check Firebase Storage and Firestore to confirm the `.wav` file and its metadata exist.
