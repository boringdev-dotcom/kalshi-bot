import type { Decision } from "../types";

export function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) {
    return <div className="empty">No would-place / would-skip / would-flatten rows yet.</div>;
  }
  const graded = decisions.some((row) => row.process_grade || row.outcome);
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Agent</th>
          <th>Action</th>
          {graded ? <th>Grade</th> : null}
          {graded ? <th>Outcome</th> : null}
          <th>Market</th>
          <th>Size</th>
          <th>Px</th>
          <th>Rem</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {decisions.map((row) => (
          <tr key={row.id}>
            <td>{row.agent}</td>
            <td>
              <span className={`chip ${row.action}`}>{row.action}</span>
            </td>
            {graded ? (
              <td>
                {row.process_grade ? <span className={`chip grade-${row.process_grade}`}>{row.process_grade}</span> : "—"}
              </td>
            ) : null}
            {graded ? <td>{row.outcome || "—"}</td> : null}
            <td>{row.market_ticker || "—"}</td>
            <td>{row.size}</td>
            <td>{row.price != null ? `${row.price}¢` : "—"}</td>
            <td>{row.rem != null ? row.rem : "—"}</td>
            <td>{row.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
