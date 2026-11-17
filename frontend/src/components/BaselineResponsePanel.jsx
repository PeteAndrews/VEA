export default function BaselineResponsePanel({ response }) {
  if (!response) return null;
  const text = response.text || "";
  return (
    <section className="panel" data-baseline-tour="response">
      <header className="panel-header">
        <h2>Student response</h2>
        <span className="badge">{response.candidate_label || `Candidate ${response.candidate_id}`}</span>
      </header>
      <div className="panel-body response-body baseline-response-body">
        {text.split(/\n+/).map((paragraph) => (
          <p key={paragraph.slice(0, 40)}>{paragraph}</p>
        ))}
      </div>
    </section>
  );
}
