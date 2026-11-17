import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate, useParams } from "react-router-dom";

import AppShell from "../components/AppShell";
import BaselineMarkingLayout from "../components/BaselineMarkingLayout";
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
    if (submitResult.destination === "questionnaire" && submitResult.route) {
      navigate(submitResult.route, { replace: true });
      return;
    }
    if (submitResult.destination === "question_selection") {
      navigate("/questions", { replace: true });
    }
  }, [submitResult, navigate]);

  if (!currentTrial || currentTrial.trial_id !== trialId) {
    return (
      <AppShell breadcrumb="Study > Baseline marking">
        <p>Loading trial...</p>
      </AppShell>
    );
  }

  const materials = currentTrial.baseline_materials;

  return (
    <AppShell breadcrumb="Study > Baseline marking">
      {!materials ? (
        <p className="error">Baseline marking materials are not available for this question.</p>
      ) : (
        <BaselineMarkingLayout
          materials={materials}
          response={currentTrial.response}
          finalMarkPanel={
            <FinalMarkPanel
              trialId={currentTrial.trial_id}
              maximumMark={currentTrial.maximum_mark}
              submitted={currentTrial.submitted}
              finalMark={currentTrial.final_mark}
            />
          }
        />
      )}
    </AppShell>
  );
}
