export default function QuestionPanel({ question }) {
  if (!question) return null;

  return (
    <section className="panel">
      <header className="panel-header">
        <h2>Question</h2>
        <span className="badge">{question.question_label}</span>
      </header>
      <div className="panel-body question-body">
        {question.stimulus.map((text) => (
          <p key={text}>{text}</p>
        ))}
        {question.instructions.map((text) => (
          <p key={text}>{text}</p>
        ))}
        {question.subparts?.length ? (
          <ul className="question-subparts">
            {question.subparts.map((text) => (
              <li key={text}>{text.replace(/^[•\-]\s*/, "")}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <footer className="panel-footer">{question.marks_text}</footer>
    </section>
  );
}
