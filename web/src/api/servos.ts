import { getJson, notifyIfUnauthorized, responseError } from "./client";

type ServoAxisState = {
  position_us: number;
  target_us: number;
  minimum_us: number;
  maximum_us: number;
  center_us: number;
};

export type ServoState = { pan: ServoAxisState; tilt: ServoAxisState };
export type ServoCommand = "left" | "right" | "up" | "down" | "center";

export function getServoState(): Promise<ServoState> {
  return getJson<ServoState>("/api/servos");
}

export async function commandServos(command: ServoCommand): Promise<ServoState> {
  const response = await fetch("/api/servos/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<ServoState>;
}
