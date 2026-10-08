import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";

import AppShell from "../components/AppShell";
import { continueQuestion, loadStudyQuestions } from "../studySlice";

function responseStatusLabel(status) {
  if (status === "submitted") return "Submitted";
  if (status === "in_progress") return "In progress";
  return "Pending";
}

export default function QuestionsPage() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { participant, questions, studyComplete, status, error } = useSelector((state) => state.study);

  useEffect(() => {
    dispatch(loadStudyQuestions());
  }, [dispatch]);

  function handleContinue(assessmentId) {
    dispatch(continueQuestion({ assessmentId })).then((result) => {
      if (result.meta.requestStatus === "fulfilled") {
        navigate(result.payload.route);
      }
    });
  }

  return (
    <AppShell breadcrumb="Study > Question selection">
      <div className="questions-page">
        <h1>Your assigned questions</h1>
        {participant ? (
          <p className="muted">
            Subject: {participant.subject} · Condition: {participant.condition}
          </p>
        ) : null}
        {status === "loading" ? <p>Loading assigned questions...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {studyComplete ? (
          <div className="study-complete-banner">
            <h2>Study complete</h2>
            <p className="muted">You have submitted final marks for all assigned questions and responses.</p>
          </div>
        ) : null}
        <div className="assessment-list">
          {questions.map((question) => (
            <section key={question.assessment_id} className="assessment-card">
              <header>
                <h2>{question.question_label || question.assessment_id}</h2>
                <span className="badge">{question.maximum_mark} marks</span>
              </header>
              <p className="muted">
                Responses completed: {question.progress.completed_responses} /{" "}
                {question.progress.total_responses}
              </p>
              <ul className="candidate-list">
                {(question.responses || []).map((response) => (
                  <li key={response.candidate_id}>
                    <span>{response.candidate_label}</span>
                    <span className={`response-status response-status-${response.status}`}>
                      {responseStatusLabel(response.status)}
                    </span>
                  </li>
                ))}
              </ul>
              {question.progress.complete ? (
                <p className="status-text">Question complete</p>
              ) : (
                <button
                  type="button"
                  className="button-link"
                  onClick={() => handleContinue(question.assessment_id)}
                >
                  {question.progress.completed_responses > 0 || question.progress.has_open_trial
                    ? "Continue next response"
                    : "Start question"}
                </button>
              )}
            </section>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
