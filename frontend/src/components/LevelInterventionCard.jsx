import { useDispatch, useSelector } from "react-redux";
import { clearLevelInterventionCard, setLevelInterventionStatus } from "../levelAiSlice";
import { launchAssistant } from "../conversationSlice";

const TYPE_LABELS = {
  NUANCE: "Nuance",
  CHALLENGE: "Challenge",
  REVIEW: "Review",
  REANCHOR: "Re-anchor",
};

export default function LevelInterventionCard({
  assessmentId,
  candidateId,
  interpretation,
  onDismiss,
}) {
  const dispatch = useDispatch();
  const { markingSessionId } = useSelector((state) => state.auth);
  const intervention = interpretation.intervention;

  if (!intervention || interpretation.status !== "pending") {
    return null;
  }

  function handleDismiss() {
    dispatch(
      setLevelInterventionStatus({
        markingSessionId,
        assessmentId,
        candidateId,
        aiId: interpretation.id,
        status: "dismissed",
      })
    );
    onDismiss?.();
  }

  function handleExplore() {
    dispatch(clearLevelInterventionCard());
    dispatch(
      launchAssistant({
        markingSessionId,
        assessmentId,
        candidateId,
        source: "explore_level",
        interpretationId: interpretation.id,
      })
    );
  }

  return (
    <div className="intervention-card level-intervention-card">
      <div className="intervention-card-header">
        <span className={`intervention-tag intervention-${intervention.type.toLowerCase()}`}>
          {TYPE_LABELS[intervention.type] || intervention.type}
        </span>
        <button type="button" className="link-button" onClick={handleDismiss}>
          Dismiss
        </button>
      </div>
      <p className="intervention-message">{intervention.message}</p>
      {intervention.nuance_items?.length ? (
        <ul className="intervention-nuance-list">
          {intervention.nuance_items.map((item) => (
            <li key={`${item.node_id}-${item.text}`}>{item.text}</li>
          ))}
        </ul>
      ) : null}
      <div className="intervention-actions">
        <button type="button" className="button-secondary" onClick={handleExplore}>
          Explore
        </button>
      </div>
    </div>
  );
}
