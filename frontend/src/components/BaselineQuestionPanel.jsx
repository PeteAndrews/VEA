export default function BaselineQuestionPanel({ question }) {
  if (!question) return null;
  return (
    <section className="panel" data-baseline-tour="question">
      <header className="panel-header">
        <h2>Question</h2>
        {question.question_ref ? <span className="badge">Q. {question.question_ref}</span> : null}
      </header>
      <div className="panel-body question-body">
        {(question.body_lines || []).map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
      {question.marks_text ? <footer className="panel-footer">{question.marks_text}</footer> : null}
    </section>
  );
}
