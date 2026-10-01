import { useDispatch, useSelector } from "react-redux";
import { setInterventionStatus } from "../aiSlice";

const TYPE_LABELS = {
  NUANCE: "Nuance",
  CHALLENGE: "Challenge",
  REVIEW: "Review",
  REANCHOR: "Re-anchor",
};

export default function InterventionCard({
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
      setInterventionStatus({
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
    dispatch(
      setInterventionStatus({
        markingSessionId,
        assessmentId,
        candidateId,
        aiId: interpretation.id,
        status: "explore",
      })
    );
  }

  return (
    <div className="intervention-card">
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
            <li key={`${item.node_id}-${item.relation}`}>
              <span className="intervention-relation">{item.relation}</span>
              {item.text}
            </li>
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
