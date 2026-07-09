export class PythonRecognitionClient {
    baseUrl;
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    async health() {
        try {
            const response = await fetch(new URL("/health", this.baseUrl));
            return response.ok;
        }
        catch {
            return false;
        }
    }
    async recognize(frame, cameraRole, cameraId) {
        const response = await this.post("/recognize", {
            imageBase64: frame.toString("base64"),
            cameraRole,
            cameraId,
        });
        return response.faces.map((face) => ({
            confidence: face.confidence,
            box: face.box,
            match: face.match,
        }));
    }
    async recognizeWithMeta(frame, cameraRole, cameraId) {
        return this.post("/recognize", {
            imageBase64: frame.toString("base64"),
            cameraRole,
            cameraId,
        });
    }
    async register(label, frame, cameraRole, cameraId) {
        return this.post("/register", {
            label,
            imageBase64: frame.toString("base64"),
            cameraRole,
            cameraId,
        });
    }
    async listFaces() {
        const response = await this.get("/faces");
        return response.faces;
    }
    async removeFace(label) {
        const response = await fetch(new URL(`/faces/${encodeURIComponent(label)}`, this.baseUrl), {
            method: "DELETE",
        });
        if (!response.ok) {
            throw await this.toError(response);
        }
        const body = (await response.json());
        return Boolean(body.removed);
    }
    async clearFaces() {
        await this.post("/faces/clear", {});
    }
    async listCameras() {
        const response = await this.get("/cameras");
        return response.cameras;
    }
    async getCamera(cameraId) {
        try {
            const response = await this.get(`/cameras/${encodeURIComponent(cameraId)}`);
            return response.camera;
        }
        catch {
            return null;
        }
    }
    async addCamera(camera) {
        const response = await this.post("/cameras", camera);
        return response.camera;
    }
    async updateCamera(cameraId, camera) {
        const response = await this.put(`/cameras/${encodeURIComponent(cameraId)}`, camera);
        return response.camera;
    }
    async deleteCamera(cameraId) {
        const response = await fetch(new URL(`/cameras/${encodeURIComponent(cameraId)}`, this.baseUrl), {
            method: "DELETE",
        });
        if (!response.ok) {
            throw await this.toError(response);
        }
        const body = (await response.json());
        return Boolean(body.removed);
    }
    async listAttendance() {
        const response = await this.get("/attendance");
        return response.attendance;
    }
    async exportAttendanceCsv() {
        const response = await fetch(new URL("/attendance.csv", this.baseUrl));
        if (!response.ok) {
            throw await this.toError(response);
        }
        return await response.text();
    }
    async get(path) {
        const response = await fetch(new URL(path, this.baseUrl));
        if (!response.ok) {
            throw await this.toError(response);
        }
        return (await response.json());
    }
    async post(path, body) {
        const response = await fetch(new URL(path, this.baseUrl), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            throw await this.toError(response);
        }
        return (await response.json());
    }
    async put(path, body) {
        const response = await fetch(new URL(path, this.baseUrl), {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            throw await this.toError(response);
        }
        return (await response.json());
    }
    async toError(response) {
        let message = `Python recognizer returned HTTP ${response.status}`;
        try {
            const body = (await response.json());
            message = body.detail ?? body.error ?? message;
        }
        catch {
            // Keep the HTTP status message if the recognizer returned non-JSON.
        }
        return new Error(message);
    }
}
//# sourceMappingURL=pythonRecognitionClient.js.map