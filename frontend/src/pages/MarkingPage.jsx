import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useParams } from "react-router-dom";
import { loadAiInterpretations, resetAi } from "../aiSlice";
import { loadLevelAiInterpretation, resetLevelAi } from "../levelAiSlice";
import AppShell from "../components/AppShell";
import ExaminerAssistantPanel from "../components/ExaminerAssistantPanel";
import CandidateInfoPanel from "../components/CandidateInfoPanel";
import IndicativeContentPanel from "../components/IndicativeContentPanel";
import LevelReviewPanel from "../components/LevelReviewPanel";
import LevelDescriptorPanel from "../components/LevelDescriptorPanel";
import QuestionPanel from "../components/QuestionPanel";
import StudentResponsePanel from "../components/StudentResponsePanel";
import { loadConversation, resetConversation } from "../conversationSlice";
import { loadJudgement, resetJudgement } from "../judgementSlice";
import { clearMarking, loadMarkingScreen } from "../markingSlice";

export default function MarkingPage({
  assessmentId: assessmentIdProp,
  candidateId: candidateIdProp,
  markingSessionId: markingSessionIdProp,
} = {}) {
  const params = useParams();
  const assessmentId = assessmentIdProp || params.assessmentId;
  const candidateId = candidateIdProp || params.candidateId;
  const dispatch = useDispatch();
  const authMarkingSessionId = useSelector((state) => state.auth.markingSessionId);
  const markingSessionId = markingSessionIdProp || authMarkingSessionId;
  const { question, levelDescriptors, indicativeContent, selectedResponse, status, error } =
    useSelector((state) => state.marking);
  const { levelContext, saving, error: judgementError } = useSelector((state) => state.judgement);
  const { error: aiError } = useSelector((state) => state.ai);
  const { error: levelAiError } = useSelector((state) => state.levelAi);
  const { error: conversationError } = useSelector((state) => state.conversation);

  useEffect(() => {
    dispatch(loadMarkingScreen({ assessmentId, candidateId }));
    return () => {
      dispatch(resetJudgement());
      dispatch(resetAi());
      dispatch(resetLevelAi());
      dispatch(resetConversation());
      dispatch(clearMarking());
    };
  }, [dispatch, assessmentId, candidateId]);

  useEffect(() => {
    if (!markingSessionId || status !== "succeeded") return;
    dispatch(loadJudgement({ markingSessionId, assessmentId, candidateId }));
    dispatch(loadAiInterpretations({ markingSessionId, assessmentId, candidateId }));
    dispatch(loadLevelAiInterpretation({ markingSessionId, assessmentId, candidateId }));
    dispatch(loadConversation({ markingSessionId, assessmentId, candidateId }));
  }, [dispatch, markingSessionId, assessmentId, candidateId, status]);

  const breadcrumb = `Marking > ${question?.question_label || "Question"} > ${
    selectedResponse?.candidate_label || `Candidate ${candidateId}`
  }`;

  return (
    <AppShell breadcrumb={breadcrumb}>
      {status === "loading" ? <p>Loading marking screen...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {judgementError ? <p className="error">{judgementError}</p> : null}
      {aiError ? <p className="error">{aiError}</p> : null}
      {levelAiError ? <p className="error">{levelAiError}</p> : null}
      {conversationError ? <p className="error">{conversationError}</p> : null}
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
          </div>
          <div className="marking-level-review">
            <LevelReviewPanel
              assessmentId={assessmentId}
              candidateId={candidateId}
              levelContext={levelContext}
            />
          </div>
          <ExaminerAssistantPanel assessmentId={assessmentId} candidateId={candidateId} />
        </div>
      ) : null}
    </AppShell>
  );
}
