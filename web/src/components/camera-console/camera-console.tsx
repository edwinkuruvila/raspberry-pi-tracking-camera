import { LogOut, MoreHorizontal } from "lucide-react";

import { useCameraConsoleData } from "@/hooks/use-camera-console-data";
import { useDetection } from "@/hooks/use-detection";

import { DetectionControls } from "./detection-controls";
import { ServoControls } from "./servo-controls";
import { StreamPanel } from "./stream-panel";

type CameraConsoleProps = {
  onLogout: () => Promise<void>;
};

export function CameraConsole({ onLogout }: CameraConsoleProps) {
  const { piHealth, checkedAt, state, error, streamUrl } = useCameraConsoleData();
  const detection = useDetection();
  const isConnecting = state === "loading";
  const isOffline = state === "error" || Boolean(piHealth && !piHealth.checks.stream_http.ok);

  return (
    <main className="camera-shell">
      <header className="camera-header">
        <details className="camera-menu">
          <summary className="utility-button" aria-label="Camera menu">
            <MoreHorizontal size={19} aria-hidden="true" />
          </summary>
          <div className="camera-menu-dropdown">
            {checkedAt ? (
              <div className="camera-menu-label">
                Checked{" "}
                {checkedAt.toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </div>
            ) : null}
            <button className="camera-menu-item" type="button" onClick={() => void onLogout()}>
              <LogOut size={15} aria-hidden="true" />
              Sign out
            </button>
          </div>
        </details>
      </header>

      <div className="camera-workspace">
        <StreamPanel
          piHealth={piHealth}
          isConnecting={isConnecting}
          isOffline={isOffline}
          streamUrl={streamUrl}
          error={error}
          detection={detection.detection}
        />
        <div className="control-sidebar">
          <ServoControls disabled={detection.detection?.follow_enabled ?? false} />
          <DetectionControls
            detection={detection.detection}
            error={detection.error}
            onChange={detection.setDetection}
          />
        </div>
      </div>
    </main>
  );
}
