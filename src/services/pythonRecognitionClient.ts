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

type RecognitionPayload = {
  imageBase64: string;
  cameraRole?: "general" | "check_in" | "check_out";
  cameraId?: string | null;
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

type PythonAttendanceResponse = {
  attendance: Array<{
    label: string;
    first_appearance: string;
    last_appearance: string;
    first_camera_role?: string;
    last_camera_role?: string;
    appearances: number;
    max_confidence: number;
  }>;
};

type PythonCamera = {
  id: string;
  name: string;
  camera_role: "general" | "check_in" | "check_out";
  rtsp_url: string;
  rtsp_username?: string | null;
  rtsp_password?: string | null;
  enabled: number;
  created_at: string;
  updated_at: string;
};

type PythonCameraResponse = {
  camera: PythonCamera;
};

type PythonCamerasResponse = {
  cameras: PythonCamera[];
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

  public async recognize(frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<DetectedFace[]> {
    const response = await this.post<PythonRecognizeResponse>("/recognize", {
      imageBase64: frame.toString("base64"),
      cameraRole,
      cameraId,
    } satisfies RecognitionPayload);
    return response.faces.map((face) => ({
      confidence: face.confidence,
      box: face.box,
      match: face.match,
    }));
  }

  public async recognizeWithMeta(frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<PythonRecognizeResponse> {
    return this.post<PythonRecognizeResponse>("/recognize", {
      imageBase64: frame.toString("base64"),
      cameraRole,
      cameraId,
    } satisfies RecognitionPayload);
  }

  public async register(label: string, frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<PythonRegisterResponse> {
    return this.post<PythonRegisterResponse>("/register", {
      label,
      imageBase64: frame.toString("base64"),
      cameraRole,
      cameraId,
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

  public async listCameras(): Promise<PythonCamera[]> {
    const response = await this.get<PythonCamerasResponse>("/cameras");
    return response.cameras;
  }

  public async getCamera(cameraId: string): Promise<PythonCamera | null> {
    try {
      const response = await this.get<PythonCameraResponse>(`/cameras/${encodeURIComponent(cameraId)}`);
      return response.camera;
    } catch {
      return null;
    }
  }

  public async addCamera(camera: {
    id?: string;
    name: string;
    cameraRole?: "general" | "check_in" | "check_out";
    rtspUrl: string;
    rtspUsername?: string | null;
    rtspPassword?: string | null;
    enabled?: boolean;
  }): Promise<PythonCamera> {
    const response = await this.post<PythonCameraResponse>("/cameras", camera);
    return response.camera;
  }

  public async updateCamera(cameraId: string, camera: {
    name: string;
    cameraRole?: "general" | "check_in" | "check_out";
    rtspUrl: string;
    rtspUsername?: string | null;
    rtspPassword?: string | null;
    enabled?: boolean;
  }): Promise<PythonCamera> {
    const response = await this.put<PythonCameraResponse>(`/cameras/${encodeURIComponent(cameraId)}`, camera);
    return response.camera;
  }

  public async deleteCamera(cameraId: string): Promise<boolean> {
    const response = await fetch(new URL(`/cameras/${encodeURIComponent(cameraId)}`, this.baseUrl), {
      method: "DELETE",
    });
    if (!response.ok) {
      throw await this.toError(response);
    }
    const body = (await response.json()) as { removed?: boolean };
    return Boolean(body.removed);
  }

  public async listAttendance(): Promise<PythonAttendanceResponse["attendance"]> {
    const response = await this.get<PythonAttendanceResponse>("/attendance");
    return response.attendance;
  }

  public async exportAttendanceCsv(): Promise<string> {
    const response = await fetch(new URL("/attendance.csv", this.baseUrl));
    if (!response.ok) {
      throw await this.toError(response);
    }
    return await response.text();
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

  private async put<T = unknown>(path: string, body: unknown): Promise<T> {
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
