import { PersonStanding } from "lucide-react";
import { useState } from "react";

import { setDetectionFollow, type DetectionState } from "@/api";

type DetectionControlsProps = {
  detection: DetectionState | null;
  error: string | null;
  onChange: (state: DetectionState) => void;
};

export function DetectionControls({ detection, error, onChange }: DetectionControlsProps) {
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const available = detection?.status !== "disabled";
  const activating =
    detection?.follow_enabled === true &&
    ["loading_model", "connecting_camera", "detecting"].includes(detection.status);

  async function toggleFollowing() {
    if (!detection) return;
    setPending(true);
    try {
      onChange(await setDetectionFollow(!detection.follow_enabled));
      setActionError(null);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to change following");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="detection-panel" aria-label="Person following">
      <button
        type="button"
        className="follow-button"
        data-active={detection?.follow_enabled || undefined}
        disabled={!detection || !available || pending || activating}
        onClick={() => void toggleFollowing()}
      >
        <PersonStanding size={19} aria-hidden="true" />
        {detection?.follow_enabled ? "Manual control" : "Track person"}
      </button>
      <div className="detection-readout" aria-live="polite">
        {detectionReadout(detection)}
      </div>
      {detection?.error || actionError || error ? (
        <p className="control-error">{detection?.error ?? actionError ?? error}</p>
      ) : null}
    </section>
  );
}

function detectionReadout(detection: DetectionState | null): string {
  if (!detection?.follow_enabled) return "Manual control";
  if (detection.sentry_mode) return "Sentry sweep";
  if (detection.camera_moving) return "Camera moving";
  if (detection.status === "online") {
    return `${detection.people.length} detected · ${detection.inference_ms} ms`;
  }

  const activatingStatus: Partial<Record<DetectionState["status"], string>> = {
    loading_model: "Loading detection model",
    connecting_camera: "Connecting to detection camera",
    detecting: "Running first detection",
  };
  return activatingStatus[detection.status] ?? detection.status.replace("_", " ");
}
