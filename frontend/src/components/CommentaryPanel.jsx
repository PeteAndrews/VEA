export default function CommentaryPanel({ commentary }) {
  if (!commentary) return null;
  return (
    <section className="panel commentary-panel" data-baseline-tour="commentary">
      <header className="panel-header">
        <h2>Commentary</h2>
      </header>
      <div className="panel-body commentary-body">
        {(commentary.paragraphs || []).map((paragraph) => (
          <p key={paragraph.slice(0, 48)}>{paragraph}</p>
        ))}
      </div>
    </section>
  );
}
