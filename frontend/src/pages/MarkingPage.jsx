import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useParams } from "react-router-dom";
import AppShell from "../components/AppShell";
import CandidateInfoPanel from "../components/CandidateInfoPanel";
import IndicativeContentPanel from "../components/IndicativeContentPanel";
import LevelContextPanel from "../components/LevelContextPanel";
import LevelDescriptorPanel from "../components/LevelDescriptorPanel";
import QuestionPanel from "../components/QuestionPanel";
import StudentResponsePanel from "../components/StudentResponsePanel";
import { loadJudgement, resetJudgement } from "../judgementSlice";
import { loadMarkingScreen } from "../markingSlice";

export default function MarkingPage() {
  const { assessmentId, candidateId } = useParams();
  const dispatch = useDispatch();
  const { markingSessionId } = useSelector((state) => state.auth);
  const { question, levelDescriptors, indicativeContent, selectedResponse, status, error } =
    useSelector((state) => state.marking);
  const { levelContext, saving, error: judgementError } = useSelector((state) => state.judgement);

  useEffect(() => {
    dispatch(loadMarkingScreen({ assessmentId, candidateId }));
    return () => {
      dispatch(resetJudgement());
    };
  }, [dispatch, assessmentId, candidateId]);

  useEffect(() => {
    if (!markingSessionId || status !== "succeeded") return;
    dispatch(loadJudgement({ markingSessionId, assessmentId, candidateId }));
  }, [dispatch, markingSessionId, assessmentId, candidateId, status]);

  const breadcrumb = `Marking > ${question?.question_label || "Question"} > ${
    selectedResponse?.candidate_label || `Candidate ${candidateId}`
  }`;

  return (
    <AppShell breadcrumb={breadcrumb}>
      {status === "loading" ? <p>Loading marking screen...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {judgementError ? <p className="error">{judgementError}</p> : null}
      {saving ? <p className="status-text">Saving judgement...</p> : null}
      {status === "succeeded" ? (
        <div className="marking-layout">
          <div className="marking-left">
            <QuestionPanel question={question} />
            <StudentResponsePanel response={selectedResponse} />
            <CandidateInfoPanel response={selectedResponse} />
          </div>
          <div className="marking-center">
            <IndicativeContentPanel
              assessmentId={assessmentId}
              candidateId={candidateId}
              indicativeContent={indicativeContent}
            />
            <LevelDescriptorPanel
              assessmentId={assessmentId}
              candidateId={candidateId}
              levels={levelDescriptors}
            />
            <LevelContextPanel levelContext={levelContext} />
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
