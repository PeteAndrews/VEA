import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate, useParams } from "react-router-dom";

import { setTrialMarkingSession } from "../authSlice";
import { loadTrial } from "../studySlice";
import FinalMarkPanel from "../components/FinalMarkPanel";
import MarkingPage from "./MarkingPage";

export default function StudyMarkingPage() {
  const { trialId } = useParams();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { currentTrial, submitResult } = useSelector((state) => state.study);

  useEffect(() => {
    dispatch(loadTrial({ trialId }));
  }, [dispatch, trialId]);

  useEffect(() => {
    if (currentTrial?.marking_session_id) {
      dispatch(setTrialMarkingSession(currentTrial.marking_session_id));
    }
  }, [dispatch, currentTrial?.marking_session_id]);

  useEffect(() => {
    if (!submitResult) return;
    if (submitResult.destination === "next_trial" && submitResult.next_trial) {
      navigate(submitResult.next_trial.route, { replace: true });
      return;
    }
    if (submitResult.destination === "question_selection") {
      navigate("/questions", { replace: true });
    }
  }, [submitResult, navigate]);

  if (!currentTrial || currentTrial.trial_id !== trialId) {
    return <p>Loading trial...</p>;
  }

  return (
    <>
      <MarkingPage
        assessmentId={currentTrial.assessment_id}
        candidateId={currentTrial.candidate_id}
        markingSessionId={currentTrial.marking_session_id}
      />
      <FinalMarkPanel
        trialId={currentTrial.trial_id}
        maximumMark={currentTrial.maximum_mark}
        submitted={currentTrial.submitted}
        finalMark={currentTrial.final_mark}
      />
    </>
  );
}
