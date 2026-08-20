import { useEffect, useState } from "react";

import { getDetectionState, type DetectionState } from "@/api";

export function useDetection() {
  const [detection, setDetection] = useState<DetectionState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let checkingAfterEventError = false;
    const events = new EventSource("/api/detection/events");
    events.onmessage = (event) => {
      if (!active) return;
      setDetection(JSON.parse(event.data) as DetectionState);
      setError(null);
    };
    events.onerror = () => {
      if (!active) return;
      setError("Detection connection interrupted");
      if (checkingAfterEventError) return;
      checkingAfterEventError = true;
      void getDetectionState()
        .then((state) => {
          if (active) setDetection(state);
        })
        .catch(() => {
          // getDetectionState dispatches the shared authentication event on 401.
        })
        .finally(() => {
          checkingAfterEventError = false;
        });
    };
    return () => {
      active = false;
      events.close();
    };
  }, []);

  return { detection, setDetection, error };
}
