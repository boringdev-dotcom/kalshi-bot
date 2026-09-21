import { api } from "../api";
import type { Status } from "../types";

export function Controls({ status, onChange }: { status: Status | null; onChange: () => void }) {
  const toLive = () => {
    const ok = window.confirm("Live mode sends real Kalshi orders. Stay on paper unless you mean it.");
    if (!ok) return;
    api.liveMode().then(onChange);
  };
  return (
    <div className="controls">
      {status?.paused ? (
        <button className="primary" onClick={() => api.resume().then(onChange)}>
          Resume
        </button>
      ) : (
        <button onClick={() => api.pause().then(onChange)}>Pause</button>
      )}
      {status?.paper !== false ? (
        <button onClick={toLive}>Switch to live</button>
      ) : (
        <button className="primary" onClick={() => api.paper().then(onChange)}>
          Back to paper
        </button>
      )}
    </div>
  );
}
