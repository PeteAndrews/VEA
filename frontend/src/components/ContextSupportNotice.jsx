import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { isContextSupportNoticeActive, setInterventionStatus } from "../aiSlice";
import { launchAssistant } from "../conversationSlice";
import { updateCodingSpan } from "../judgementSlice";
import { snippet } from "../responseUtils";

export default function ContextSupportNotice({ assessmentId, candidateId, interpretation, coding }) {
  const dispatch = useDispatch();
  const [confirming, setConfirming] = useState(false);
  const { markingSessionId } = useSelector((state) => state.auth);
  const { saving } = useSelector((state) => state.judgement);
  const { launchStatus } = useSelector((state) => state.conversation);
  const suggested =
    interpretation.suggested_evidence_span || interpretation.suggested_span;

  if (!isContextSupportNoticeActive(interpretation)) {
    return null;
  }

  function handleKeepAsIs() {
    dispatch(
      setInterventionStatus({
        markingSessionId,
        assessmentId,
        candidateId,
        aiId: interpretation.id,
        status: "dismissed",
      })
    );
  }

  function handleExplore() {
    dispatch(
      launchAssistant({
        markingSessionId,
        assessmentId,
        candidateId,
        source: "explore",
        codingId: interpretation.coding_id,
        interpretationId: interpretation.id,
      })
    );
  }

  function handleAdjustCode() {
    if (!suggested) return;
    setConfirming(true);
  }

  function handleConfirmAdjust() {
    if (!suggested) return;
    dispatch(
      updateCodingSpan({
        markingSessionId,
        assessmentId,
        candidateId,
        codingId: coding.id,
        draft: {
          start_char: suggested.start_char,
          end_char: suggested.end_char,
          text: suggested.text,
        },
      })
    );
    setConfirming(false);
  }

  return (
    <div className="context-support-notice">
      <p className="context-support-message">
        {interpretation.intervention?.message ||
          "More evidence is needed for this link. The nearby response contains the missing evidence."}
      </p>
      {confirming && suggested ? (
        <div className="context-support-confirm">
          <p>
            Expand coded evidence to: &ldquo;{snippet(suggested.text, 120)}&rdquo;
          </p>
          <div className="context-support-actions">
            <button
              type="button"
              className="button-primary"
              disabled={saving}
              onClick={handleConfirmAdjust}
            >
              Confirm expand
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={saving}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="context-support-actions">
          <button
            type="button"
            className="button-secondary"
            disabled={!suggested || saving}
            onClick={handleAdjustCode}
          >
            Adjust code
          </button>
          <button type="button" className="button-secondary" onClick={handleKeepAsIs}>
            Keep as is
          </button>
          <button
            type="button"
            className="button-secondary"
            disabled={launchStatus === "loading"}
            onClick={handleExplore}
          >
            Explore
          </button>
        </div>
      )}
    </div>
  );
}
