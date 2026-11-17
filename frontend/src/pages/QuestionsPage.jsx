import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";

import AppShell from "../components/AppShell";
import { continueQuestion, loadStudyQuestions } from "../studySlice";

function responseStatusLabel(status) {
  if (status === "submitted") return "Submitted";
  if (status === "in_progress") return "In progress";
  return "Pending";
}

function QuestionCard({ question, disabled, onContinue }) {
  return (
    <section className="assessment-card">
      <header>
        <h2>{question.question_label || question.assessment_id}</h2>
        <span className="badge">{question.maximum_mark} marks</span>
      </header>
      <p className="muted">
        Responses completed: {question.progress.completed_responses} / {question.progress.total_responses}
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
          disabled={disabled}
          onClick={() => onContinue(question.assessment_id)}
        >
          {question.progress.completed_responses > 0 || question.progress.has_open_trial
            ? "Continue next response"
            : "Start question"}
        </button>
      )}
    </section>
  );
}

function WalkthroughCard({ walkthrough, needsWalkthrough, navigate, route, conditionLocked, label }) {
  if (!walkthrough?.required) return null;
  const disabled = conditionLocked || !walkthrough.accessible;
  return (
    <section className="assessment-card">
      <header>
        <h2>{label || "Practice walkthrough"}</h2>
      </header>
      <p className="muted">
        {conditionLocked
          ? "Complete the previous condition before starting this walkthrough."
          : needsWalkthrough
            ? "Complete this before the experimental marking tasks in this condition."
            : "You have completed the practice walkthrough."}
      </p>
      <button
        type="button"
        className="button-link"
        disabled={disabled}
        onClick={() => navigate(route)}
      >
        {needsWalkthrough ? "Start walkthrough" : "Open walkthrough"}
      </button>
    </section>
  );
}

const POST_CONDITION_QUESTIONNAIRES = [
  { key: "nasa_tlx_raw", label: "NASA-TLX" },
  { key: "sus", label: "System Usability Scale" },
  { key: "ueq", label: "User Experience Questionnaire" },
];

function ConditionQuestionnaires({ block, progress, navigate }) {
  const row = (progress?.conditions || []).find((item) => item.condition === block.condition);
  const submitted = row?.questionnaires || {};
  const nextOpen = POST_CONDITION_QUESTIONNAIRES.find((item) => !submitted[item.key]);
  const markingReady = Boolean(row?.marking_complete) && !block.locked;

  return (
    <section className="assessment-card">
      <header>
        <h2>Questionnaires</h2>
      </header>
      <p className="muted">
        {markingReady
          ? "These concern the experimental marking you have just finished, in this order."
          : "NASA-TLX, the System Usability Scale and the User Experience Questionnaire open after the experimental marks for this condition are submitted."}
      </p>
      <ul className="candidate-list">
        {POST_CONDITION_QUESTIONNAIRES.map((item) => {
          const done = Boolean(submitted[item.key]);
          const available = markingReady && nextOpen?.key === item.key;
          return (
            <li key={item.key}>
              <span>{item.label}</span>
              {done ? (
                <span className="response-status response-status-submitted">Submitted</span>
              ) : available ? (
                <button
                  type="button"
                  className="button-link"
                  onClick={() => navigate(`/study/questionnaire/${item.key}/${block.condition}`)}
                >
                  Start
                </button>
              ) : (
                <span className="response-status">Waiting</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ConditionSection({ block, progress, navigate, onContinue }) {
  const veaTour = block.walkthrough;
  const baselineTour = block.baseline_walkthrough;
  const veaNeedsWalkthrough = Boolean(veaTour?.required && !veaTour?.completed);
  const baselineNeedsWalkthrough = Boolean(baselineTour?.required && !baselineTour?.completed);
  const markingDisabled = block.locked || veaNeedsWalkthrough || baselineNeedsWalkthrough;

  return (
    <section
      className={`condition-block condition-block-${block.condition}${block.locked ? " condition-block-locked" : ""}`}
    >
      <header className="condition-block-header">
        <h2>{block.label}</h2>
        {block.locked ? <span className="badge muted">Complete the previous condition first</span> : null}
        {block.complete && !block.locked ? <span className="badge">Complete</span> : null}
      </header>
      {block.condition === "vea" ? (
        <WalkthroughCard
          walkthrough={veaTour}
          needsWalkthrough={veaNeedsWalkthrough}
          navigate={navigate}
          route="/study/walkthrough"
          conditionLocked={block.locked}
          label="VEA practice walkthrough"
        />
      ) : null}
      {block.condition === "baseline" && baselineTour?.required ? (
        <WalkthroughCard
          walkthrough={baselineTour}
          needsWalkthrough={baselineNeedsWalkthrough}
          navigate={navigate}
          route="/study/baseline-walkthrough"
          conditionLocked={block.locked}
          label="Baseline practice walkthrough"
        />
      ) : null}
      <div className="assessment-list">
        {block.missing_experimental_config || block.questions.length === 0 ? (
          <p className="muted">Experimental questions for this condition still need to be assigned.</p>
        ) : (
          block.questions.map((question) => (
            <QuestionCard
              key={question.assessment_id}
              question={question}
              disabled={markingDisabled}
              onContinue={onContinue}
            />
          ))
        )}
      </div>
      <ConditionQuestionnaires block={block} progress={progress} navigate={navigate} />
    </section>
  );
}

export default function QuestionsPage() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const {
    participant,
    questions,
    conditions,
    layout,
    studyComplete,
    status,
    error,
    walkthrough,
    baselineWalkthrough,
    missingExperimentalConfig,
    progress,
  } = useSelector((state) => state.study);
  const [continueError, setContinueError] = useState("");

  useEffect(() => {
    let cancelled = false;
    dispatch(loadStudyQuestions()).then((result) => {
      if (cancelled || result.meta.requestStatus !== "fulfilled") return;
      const next = result.payload.progress?.next;
      if (next?.stage === "questionnaire" && next.key === "background" && next.route) {
        navigate(next.route, { replace: true });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [dispatch, navigate]);

  const showWalkthrough = Boolean(walkthrough?.required) && layout !== "within";
  const needsWalkthrough = Boolean(showWalkthrough && !walkthrough.completed);
  const showBaselineWalkthrough = Boolean(baselineWalkthrough?.required) && layout !== "within";
  const needsBaselineWalkthrough = Boolean(showBaselineWalkthrough && !baselineWalkthrough.completed);
  const singleMarkingDisabled = needsWalkthrough || needsBaselineWalkthrough;

  function handleContinue(assessmentId) {
    setContinueError("");
    dispatch(continueQuestion({ assessmentId })).then((result) => {
      if (result.meta.requestStatus === "fulfilled") {
        navigate(result.payload.route);
        return;
      }
      if (result.meta.requestStatus === "rejected") {
        setContinueError(result.error?.message || "Could not open this question");
      }
    });
  }

  return (
    <AppShell breadcrumb="Study > Question selection">
      <div className="questions-page">
        <h1>Your assigned questions</h1>
        {participant ? (
          <p className="muted">
            Subject: {participant.subject}
            {participant.condition === "within" ? " · Within-subjects study" : ` · Condition: ${participant.condition}`}
          </p>
        ) : null}
        {status === "loading" ? <p>Loading assigned questions...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {continueError ? <p className="error">{continueError}</p> : null}
        {showWalkthrough ? (
          <WalkthroughCard
            walkthrough={walkthrough}
            needsWalkthrough={needsWalkthrough}
            navigate={navigate}
            route="/study/walkthrough"
            conditionLocked={false}
            label="VEA practice walkthrough"
          />
        ) : null}
        {showBaselineWalkthrough ? (
          <WalkthroughCard
            walkthrough={baselineWalkthrough}
            needsWalkthrough={needsBaselineWalkthrough}
            navigate={navigate}
            route="/study/baseline-walkthrough"
            conditionLocked={false}
            label="Baseline practice walkthrough"
          />
        ) : null}
        {studyComplete ? (
          <div className="study-complete-banner">
            <h2>Study complete</h2>
            <p className="muted">You have finished the assigned marking and questionnaires.</p>
          </div>
        ) : null}
        {layout === "within" && conditions?.length ? (
          <div className="condition-list">
            {conditions.map((block) => (
              <ConditionSection
                key={block.condition}
                block={block}
                progress={progress}
                navigate={navigate}
                onContinue={handleContinue}
              />
            ))}
          </div>
        ) : (
          <div className="assessment-list">
            {missingExperimentalConfig && !questions.length ? (
              <p className="muted">Experimental questions still need to be assigned for this participant.</p>
            ) : (
              questions.map((question) => (
                <QuestionCard
                  key={question.assessment_id}
                  question={question}
                  disabled={singleMarkingDisabled}
                  onContinue={handleContinue}
                />
              ))
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
