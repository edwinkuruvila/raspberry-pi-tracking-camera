import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, LocateFixed } from "lucide-react";
import { useEffect, useState } from "react";

import { commandServos, getServoState, type ServoCommand, type ServoState } from "@/api";

type ServoControlsProps = {
  disabled?: boolean;
};

export function ServoControls({ disabled = false }: ServoControlsProps) {
  const [servoState, setServoState] = useState<ServoState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    getServoState()
      .then((nextState) => {
        if (!cancelled) {
          setServoState(nextState);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Servo controller unavailable");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function sendCommand(command: ServoCommand) {
    try {
      setServoState(await commandServos(command));
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to move camera";
      setError(message);
    }
  }

  return (
    <section className="control-panel" aria-label="Camera position">
      <div className="control-grid">
        <DirectionButton
          label="Tilt up"
          command="up"
          disabled={disabled}
          gridColumn={2}
          gridRow={1}
          onCommand={sendCommand}
        >
          <ArrowUp size={21} aria-hidden="true" />
        </DirectionButton>
        <DirectionButton
          label="Pan left"
          command="left"
          disabled={disabled}
          gridColumn={1}
          gridRow={2}
          onCommand={sendCommand}
        >
          <ArrowLeft size={21} aria-hidden="true" />
        </DirectionButton>
        <DirectionButton
          label="Center camera"
          command="center"
          disabled={disabled}
          gridColumn={2}
          gridRow={2}
          onCommand={sendCommand}
        >
          <LocateFixed size={20} aria-hidden="true" />
        </DirectionButton>
        <DirectionButton
          label="Pan right"
          command="right"
          disabled={disabled}
          gridColumn={3}
          gridRow={2}
          onCommand={sendCommand}
        >
          <ArrowRight size={21} aria-hidden="true" />
        </DirectionButton>
        <DirectionButton
          label="Tilt down"
          command="down"
          disabled={disabled}
          gridColumn={2}
          gridRow={3}
          onCommand={sendCommand}
        >
          <ArrowDown size={21} aria-hidden="true" />
        </DirectionButton>
      </div>

      {servoState ? (
        <div className="control-readout">
          <div className="control-readout-values">
            <span>Pan {servoState.pan.target_us} µs</span>
            <span>Tilt {servoState.tilt.target_us} µs</span>
          </div>
        </div>
      ) : null}

      {error ? <p className="control-error">{error}</p> : null}
    </section>
  );
}

type DirectionButtonProps = {
  label: string;
  command: ServoCommand;
  disabled: boolean;
  gridColumn: number;
  gridRow: number;
  onCommand: (command: ServoCommand) => Promise<void>;
  children: React.ReactNode;
};

function DirectionButton({ label, command, disabled, gridColumn, gridRow, onCommand, children }: DirectionButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={() => void onCommand(command)}
      className="control-button"
      data-command={command}
      style={{ gridColumn, gridRow }}
    >
      {children}
    </button>
  );
}
