import { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";

import { completeBaselineWalkthrough, startBaselineWalkthrough } from "../api";
import AppShell from "../components/AppShell";
import BaselineMarkingLayout from "../components/BaselineMarkingLayout";
import FinalMarkPanel from "../components/FinalMarkPanel";
import BaselineWalkthroughOverlay from "../baselineWalkthrough/BaselineWalkthroughOverlay";
import { setTrialMarkingSession } from "../authSlice";
import { markBaselineWalkthroughComplete } from "../studySlice";

export default function BaselineWalkthroughPage() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSession(null);
    setError(null);
    startBaselineWalkthrough()
      .then((payload) => {
        if (cancelled) return;
        setSession(payload);
        dispatch(setTrialMarkingSession(payload.marking_session_id));
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  async function handleFinalMark(mark) {
    setSubmitting(true);
    try {
      await completeBaselineWalkthrough(session.marking_session_id, mark);
      dispatch(markBaselineWalkthroughComplete());
      navigate("/questions", { replace: true });
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <AppShell breadcrumb="Study > Baseline practice">
        <p className="error walkthrough-error">{error}</p>
      </AppShell>
    );
  }

  if (!session) {
    return (
      <AppShell breadcrumb="Study > Baseline practice">
        <p>Loading practice session...</p>
      </AppShell>
    );
  }

  return (
    <AppShell breadcrumb="Study > Baseline practice">
      <BaselineMarkingLayout
        materials={session.baseline_materials}
        response={session.response}
        finalMarkPanel={
          <FinalMarkPanel
            trialId="baseline-walkthrough"
            maximumMark={session.maximum_mark}
            onSubmit={handleFinalMark}
          />
        }
      />
      <BaselineWalkthroughOverlay submitting={submitting} />
    </AppShell>
  );
}
