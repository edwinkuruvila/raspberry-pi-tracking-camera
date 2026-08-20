import { getJson, notifyIfUnauthorized, responseError } from "./client";

export type DetectionPerson = {
  track_id: number;
  confidence: number;
  left: number;
  top: number;
  width: number;
  height: number;
  observed: boolean;
  confirmed: boolean;
  selected: boolean;
};

export type DetectionGuidance = {
  track_id: number;
  center_x: number;
  center_y: number;
  error_x: number;
  error_y: number;
  pan: "left" | "right" | "hold";
  tilt: "up" | "down" | "hold";
};

export type DetectionState = {
  status:
    | "disabled"
    | "idle"
    | "loading_model"
    | "connecting_camera"
    | "detecting"
    | "online"
    | "camera_unavailable"
    | "error";
  people: DetectionPerson[];
  target_id: number | null;
  guidance: DetectionGuidance | null;
  camera_moving: boolean;
  sentry_mode: boolean;
  inference_ms: number;
  updated_at: number;
  follow_enabled: boolean;
  error: string | null;
};

export function getDetectionState(): Promise<DetectionState> {
  return getJson<DetectionState>("/api/detection");
}

export async function setDetectionFollow(enabled: boolean): Promise<DetectionState> {
  const response = await fetch("/api/detection/follow", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<DetectionState>;
}
