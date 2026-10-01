import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { fetchAssessments, fetchCandidates } from "../assessmentsSlice";

export default function QuestionsPage() {
  const dispatch = useDispatch();
  const { items, candidatesByAssessment, status, error } = useSelector(
    (state) => state.assessments
  );

  useEffect(() => {
    dispatch(fetchAssessments());
  }, [dispatch]);

  useEffect(() => {
    for (const assessment of items) {
      if (!candidatesByAssessment[assessment.assessment_id]) {
        dispatch(fetchCandidates(assessment.assessment_id));
      }
    }
  }, [dispatch, items, candidatesByAssessment]);

  return (
    <AppShell breadcrumb="Marking > Question selection">
      <div className="questions-page">
        <h1>Select a question</h1>
        {status === "loading" ? <p>Loading assessments...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        <div className="assessment-list">
          {items.map((assessment) => (
            <section key={assessment.assessment_id} className="assessment-card">
              <header>
                <h2>{assessment.question_label}</h2>
                <span className="badge">{assessment.max_mark} marks</span>
              </header>
              <p className="muted">
                {assessment.candidate_count} candidate
                {assessment.candidate_count === 1 ? "" : "s"} available
              </p>
              <ul className="candidate-list">
                {(candidatesByAssessment[assessment.assessment_id] || []).map((candidate) => (
                  <li key={candidate.candidate_id}>
                    <span>{candidate.candidate_label}</span>
                    <span className="muted">{candidate.word_count} words</span>
                    <Link
                      to={`/mark/${assessment.assessment_id}/${candidate.candidate_id}`}
                      className="button-link"
                    >
                      Open for marking
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
