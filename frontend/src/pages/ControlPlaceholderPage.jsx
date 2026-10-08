import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate, useParams } from "react-router-dom";

import AppShell from "../components/AppShell";
import FinalMarkPanel from "../components/FinalMarkPanel";
import { setTrialMarkingSession } from "../authSlice";
import { loadTrial } from "../studySlice";

export default function ControlPlaceholderPage() {
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
    <AppShell breadcrumb="Study > Control condition">
      <div className="control-placeholder">
        <h1>Control marking interface</h1>
        <p className="muted">
          Placeholder for the non-VEA marking experience. Submit a final mark to continue the study.
        </p>
        <p>
          Question: <strong>{currentTrial.assessment_id}</strong>
        </p>
        <p>
          Response: <strong>{currentTrial.candidate_id}</strong>
        </p>
        <FinalMarkPanel
          trialId={currentTrial.trial_id}
          maximumMark={currentTrial.maximum_mark}
          submitted={currentTrial.submitted}
          finalMark={currentTrial.final_mark}
        />
      </div>
    </AppShell>
  );
}
