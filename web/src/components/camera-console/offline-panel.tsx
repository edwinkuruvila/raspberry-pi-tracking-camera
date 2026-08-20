export function OfflinePanel({ detail }: { detail?: string }) {
  return (
    <div className="empty-state">
      <strong>Camera offline</strong>
      <p>The live stream is unavailable. Check that the Pi is powered on and MediaMTX is running.</p>
      {detail ? <p className="stream-detail">{detail}</p> : null}
    </div>
  );
}
