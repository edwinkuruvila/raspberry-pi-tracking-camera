import type { CSSProperties } from "react";

import type { DetectionPerson, DetectionState } from "@/api";

type DetectionOverlayProps = {
  detection: DetectionState | null;
};

export function DetectionOverlay({ detection }: DetectionOverlayProps) {
  if (detection?.status !== "online") {
    return null;
  }

  return (
    <div className="detection-overlay" aria-hidden="true">
      <div className="detection-dead-zone" />
      {detection.people.map((person) => (
        <PersonBox key={person.track_id} person={person} />
      ))}
      {detection.guidance ? (
        <div
          className="detection-target"
          style={{
            left: `${detection.guidance.center_x * 100}%`,
            top: `${detection.guidance.center_y * 100}%`,
          }}
        />
      ) : null}
    </div>
  );
}

function PersonBox({ person }: { person: DetectionPerson }) {
  const style = {
    "--box-left": `${person.left * 100}%`,
    "--box-top": `${person.top * 100}%`,
    "--box-width": `${person.width * 100}%`,
    "--box-height": `${person.height * 100}%`,
  } as CSSProperties;

  return (
    <div className="detection-box" data-selected={person.selected || undefined} style={style}>
      <span>
        {person.selected ? "target" : "person"} {Math.round(person.confidence * 100)}%
      </span>
    </div>
  );
}
