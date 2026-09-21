import { api } from "../api";
import type { Status } from "../types";

export function Controls({ status, onChange }: { status: Status | null; onChange: () => void }) {
  return (
    <div className="controls">
      {status?.paused ? (
        <button className="primary" onClick={() => api.resume().then(onChange)}>
          Resume
        </button>
      ) : (
        <button onClick={() => api.pause().then(onChange)}>Pause</button>
      )}
      {status?.paper ? (
        <button onClick={() => api.liveMode().then(onChange)}>Switch to live</button>
      ) : (
        <button className="primary" onClick={() => api.paper().then(onChange)}>
          Switch to paper
        </button>
      )}
    </div>
  );
}
