# Mute Scribe Decoupling Plan

This document outlines the strategy for decoupling the Mute Scribe frontend and backend to allow hosting on separate virtual machines (VMs).

## Current Architecture (Coupled)
- **Backend (`main_scribe.py`)**: Acts as both the API server and the static file server for the frontend.
- **Frontend (`frontend_scribe/`)**: Relies on `window.location.host` to establish WebSocket connections and make API calls.

## Proposed Architecture (Decoupled)
- **Frontend VM (Static Host)**: Serves `index.html`, `js`, and `css`. Communicates with the backend via public IP/Domain.
- **Backend VM (API/WebSocket Server)**: Handles Gemini Live sessions and transcript analysis.

---

## Implementation Strategy

### 1. Frontend Enhancements (`frontend_scribe/`)

#### Dynamic Backend Configuration
Currently, `gemini-client.js` hardcodes the WebSocket URL to the current window host. We will modify it to accept a configurable backend address.

- **`gemini-client.js`**: Update the `connect()` method to accept a `backendUrl`.
- **`main.js`**: 
    - Inject the backend URL (e.g., from a config file or environment variable).
    - Update the `fetch` call for `/api/analyze` to use the absolute URL of the backend VM.

### 2. Backend Enhancements (`main_scribe.py`)

#### API-Only Mode
The backend should focus strictly on processing audio and providing analysis.

- **Remove Static Routes**: Delete `app.mount("/static", ...)` and the root `@app.get("/")` route.
- **Network Accessibility**: Change `uvicorn.run(host="localhost")` to `host="0.0.0.0"` to ensure the service is reachable from external IPs.
- **CORS Safety**: Ensure `CORSMiddleware` is configured to allow requests from the Frontend VM's IP or domain.

---

## Deployment Steps

### Step 1: Backend VM Setup
1. **Environment**: Install Python 3.10+ and requirements from `gemini-live-genai-python-sdk/requirements.txt`.
2. **Secrets**: Set `GEMINI_API_KEY` in a `.env` file.
3. **Firewall**: Open the application port (default `8000`) for inbound traffic.
4. **Execution**: Run `python main_scribe.py`.

### Step 2: Frontend VM Setup
1. **Assets**: Transfer the `frontend_scribe/` directory to the VM.
2. **Configuration**: Update the backend URL in the JavaScript logic to point to `http://<BACKEND_VM_IP>:8000`.
3. **Web Server**: Use Nginx or a simple static server to host the files.
   ```bash
   # Example using Python's built-in server
   python3 -m http.server 80
   ```

---

## Verification Plan
1. Start the backend on one port (e.g., 8000).
2. Start a static server for the frontend on another port (e.g., 8080).
3. Verify that the frontend can successfully open a WebSocket to port 8000 and receive transcriptions.
4. Verify that "End & Analyze" successfully posts to the API on port 8000.
