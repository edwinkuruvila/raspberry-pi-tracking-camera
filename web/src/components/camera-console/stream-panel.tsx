import type { DetectionState, PiHealth } from "@/api";

import { ConnectingIndicator } from "./connecting-indicator";
import { DetectionOverlay } from "./detection-overlay";
import { OfflinePanel } from "./offline-panel";

type StreamPanelProps = {
  piHealth: PiHealth | null;
  isConnecting: boolean;
  isOffline: boolean;
  streamUrl: string | null;
  error: string | null;
  detection: DetectionState | null;
};

export function StreamPanel({ piHealth, isConnecting, isOffline, streamUrl, error, detection }: StreamPanelProps) {
  return (
    <section className="stream-frame" aria-label="Live camera stream">
      <div className="stream-overlay">
        {isConnecting ? (
          <ConnectingIndicator />
        ) : isOffline ? (
          <OfflinePanel detail={error ?? piHealth?.checks.stream_http.detail} />
        ) : !streamUrl ? (
          <ConnectingIndicator />
        ) : (
          <>
            <iframe
              title="Room camera live stream"
              src={`${streamUrl}?controls=false&autoplay=true&muted=true&playsInline=true`}
              width="100%"
              height="100%"
              frameBorder="0"
            />
            <DetectionOverlay detection={detection} />
          </>
        )}
      </div>
    </section>
  );
}
