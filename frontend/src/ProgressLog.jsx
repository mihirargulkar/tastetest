import { foundTags, scoreSteps, signatureSteps } from "./progress";

export default function ProgressLog({ kind, trace, storeCount }) {
  const steps = kind === "signature" ? signatureSteps(trace) : scoreSteps(trace, storeCount);
  const tags = kind === "signature" ? foundTags(trace) : [];
  return (
    <ol className="progress" aria-live="polite" aria-label="Run progress">
      {steps.map((s, i) => (
        <li key={s.label} className={`step ${s.state}`}>
          <span className="step-mark" aria-hidden="true">{s.state === "done" ? "✓" : ""}</span>
          <span className="step-body">
            <span className={s.state === "now" ? "step-label shimmer" : "step-label"}>{s.label}</span>
            {s.detail && <span className="step-detail"> · {s.detail}</span>}
            {kind === "signature" && i === 1 && tags.length > 0 && (
              <span className="found">{tags.map((name) => <span key={name} className="chip found-chip">{name}</span>)}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}
