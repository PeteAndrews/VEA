export default function CandidateInfoPanel({ response }) {
  if (!response) return null;

  return (
    <section className="panel">
      <header className="panel-header">
        <h2>Candidate Info</h2>
      </header>
      <div className="panel-body candidate-grid">
        <div>
          <div className="field-label">Name</div>
          <div className="field-value">{response.candidate_label}</div>
        </div>
        <div>
          <div className="field-label">Candidate No.</div>
          <div className="field-value muted">Not recorded</div>
        </div>
        <div>
          <div className="field-label">Script</div>
          <div className="field-value muted">Not recorded</div>
        </div>
        <div>
          <div className="field-label">Variant</div>
          <div className="field-value muted">Not recorded</div>
        </div>
      </div>
    </section>
  );
}
