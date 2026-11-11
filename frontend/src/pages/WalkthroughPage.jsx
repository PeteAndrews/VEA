import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";

import { completeWalkthrough, setRequestInterceptor, startWalkthrough } from "../api";
import { setTrialMarkingSession } from "../authSlice";
import FinalMarkPanel from "../components/FinalMarkPanel";
import MarkingPage from "./MarkingPage";
import { store } from "../store";
import { markWalkthroughComplete } from "../studySlice";
import WalkthroughOverlay from "../walkthrough/WalkthroughOverlay";
import {
  activateWalkthroughReplay,
  deactivateWalkthroughReplay,
  handleWalkthroughRequest,
} from "../walkthrough/replay";

export default function WalkthroughPage() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const walkthrough = useSelector((state) => state.study.walkthrough);
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!walkthrough?.required) {
      if (walkthrough) navigate("/questions", { replace: true });
      return undefined;
    }
    let cancelled = false;
    setSession(null);
    setError(null);
    activateWalkthroughReplay();
    setRequestInterceptor(handleWalkthroughRequest);
    startWalkthrough()
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
      setRequestInterceptor(null);
      deactivateWalkthroughReplay();
    };
  }, [dispatch, navigate, walkthrough?.required]);

  async function handleFinalMark(mark) {
    const level3 = store.getState().marking.levelDescriptors.find((level) => level.level === 3);
    const range = level3?.mark_range;
    if (range && (mark < range.min || mark > range.max)) {
      throw new Error(`Choose a mark in Level 3 (${range.min}–${range.max}).`);
    }
    await completeWalkthrough(session.marking_session_id, mark);
    dispatch(markWalkthroughComplete());
    navigate("/questions");
  }

  return (
    <>
      {error ? <p className="error walkthrough-error">{error}</p> : null}
      {session ? (
        <>
          <MarkingPage
            key={session.marking_session_id}
            assessmentId={session.assessment_id}
            candidateId={session.candidate_id}
            markingSessionId={session.marking_session_id}
            finalMarkPanel={
              <FinalMarkPanel
                trialId="walkthrough"
                maximumMark={session.maximum_mark}
                onSubmit={handleFinalMark}
              />
            }
          />
          <WalkthroughOverlay />
        </>
      ) : error ? null : (
        <p className="walkthrough-error">Starting the practice walkthrough…</p>
      )}
    </>
  );
}
