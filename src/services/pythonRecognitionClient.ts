import type { DetectedFace } from "../detector/types.js";

type PythonMatch = {
  label: string;
  score: number;
  confidence: number;
  sampleCount: number;
} | null;

type PythonFace = {
  confidence: number;
  box: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  match: PythonMatch;
};

type PythonRecognizeResponse = {
  faces: PythonFace[];
  snapshot?: {
    path: string;
    timestamp: string;
    confidence: number;
  } | null;
  state?: string;
};

type PythonRegisterResponse = {
  label: string;
  sampleCount: number;
  updatedAt: string;
};

type PythonFaceListResponse = {
  faces: Array<{
    label: string;
    sampleCount: number;
    updatedAt: string;
  }>;
};

export class PythonRecognitionClient {
  public constructor(private readonly baseUrl: string) {}

  public async health(): Promise<boolean> {
    try {
      const response = await fetch(new URL("/health", this.baseUrl));
      return response.ok;
    } catch {
      return false;
    }
  }

  public async recognize(frame: Buffer): Promise<DetectedFace[]> {
    const response = await this.post<PythonRecognizeResponse>("/recognize", {
      imageBase64: frame.toString("base64"),
    });
    return response.faces.map((face) => ({
      confidence: face.confidence,
      box: face.box,
      match: face.match,
    }));
  }

  public async recognizeWithMeta(frame: Buffer): Promise<PythonRecognizeResponse> {
    return this.post<PythonRecognizeResponse>("/recognize", {
      imageBase64: frame.toString("base64"),
    });
  }

  public async register(label: string, frame: Buffer): Promise<PythonRegisterResponse> {
    return this.post<PythonRegisterResponse>("/register", {
      label,
      imageBase64: frame.toString("base64"),
    });
  }

  public async listFaces(): Promise<PythonFaceListResponse["faces"]> {
    const response = await this.get<PythonFaceListResponse>("/faces");
    return response.faces;
  }

  public async removeFace(label: string): Promise<boolean> {
    const response = await fetch(new URL(`/faces/${encodeURIComponent(label)}`, this.baseUrl), {
      method: "DELETE",
    });
    if (!response.ok) {
      throw await this.toError(response);
    }
    const body = (await response.json()) as { removed?: boolean };
    return Boolean(body.removed);
  }

  public async clearFaces(): Promise<void> {
    await this.post("/faces/clear", {});
  }

  private async get<T>(path: string): Promise<T> {
    const response = await fetch(new URL(path, this.baseUrl));
    if (!response.ok) {
      throw await this.toError(response);
    }
    return (await response.json()) as T;
  }

  private async post<T = unknown>(path: string, body: unknown): Promise<T> {
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
    return (await response.json()) as T;
  }

  private async toError(response: Response): Promise<Error> {
    let message = `Python recognizer returned HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string; error?: string };
      message = body.detail ?? body.error ?? message;
    } catch {
      // Keep the HTTP status message if the recognizer returned non-JSON.
    }
    return new Error(message);
  }
}
