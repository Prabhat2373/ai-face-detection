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
    async recognize(frame) {
        const response = await this.post("/recognize", {
            imageBase64: frame.toString("base64"),
        });
        return response.faces.map((face) => ({
            confidence: face.confidence,
            box: face.box,
            match: face.match,
        }));
    }
    async recognizeWithMeta(frame) {
        return this.post("/recognize", {
            imageBase64: frame.toString("base64"),
        });
    }
    async register(label, frame) {
        return this.post("/register", {
            label,
            imageBase64: frame.toString("base64"),
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