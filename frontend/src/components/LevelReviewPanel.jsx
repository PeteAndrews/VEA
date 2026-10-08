import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { launchAssistant } from "../conversationSlice";
export default function LevelReviewPanel({ assessmentId, candidateId, levelContext }) {
  const dispatch = useDispatch();
  const { markingSessionId } = useSelector((state) => state.auth);
  const { interpretation, checking } = useSelector((state) => state.levelAi);
  const [showMappedEvidence, setShowMappedEvidence] = useState(false);

  if (!levelContext) return null;

  const summary = interpretation?.summary;
  const level = levelContext.level;

  function handleVerify() {
    if (!interpretation?.id) return;
    dispatch(
      launchAssistant({
        markingSessionId,
        assessmentId,
        candidateId,
        source: "verify_level",
        interpretationId: interpretation.id,
      })
    );
  }

  return (
    <section className="panel panel-wide level-review-panel">
      <header className="panel-header level-review-header">
        <div>
          <h2>Level {level} review</h2>
          <span className="tag tag-tentative">Tentative</span>
        </div>
        {checking ? <span className="checking-dot" title="Checking level" /> : null}
      </header>

      <div className="panel-body level-review-body">
        <p className="level-review-descriptor">{summary?.descriptor_text || levelContext.text}</p>

        {summary ? (
          <p className="level-review-status">
            <span className="level-review-status-label">AI check:</span>{" "}
            {summary.ai_check_label}
          </p>
        ) : checking ? (
          <p className="muted">Running level check…</p>
        ) : null}

        {summary?.evidence_mapped?.length ? (
          <div className="level-review-section">
            <h3>Evidence mapped</h3>
            <ul className="level-review-checklist">
              {summary.evidence_mapped.map((item) => (
                <li key={item.criterion_id}>
                  <span className="check-icon">✓</span>
                  {item.label}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {summary?.needs_attention?.length ? (
          <div className="level-review-section level-review-attention">
            <h3>Needs attention</h3>
            <ul className="level-review-attention-list">
              {summary.needs_attention.map((item) => (
                <li key={item}>
                  <span className="attention-icon">?</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {summary?.key_guidance ? (
          <div className="level-review-section">
            <h3>Key guidance</h3>
            <p className="level-review-guidance">{summary.key_guidance}</p>
          </div>
        ) : null}

        {showMappedEvidence && summary?.mapped_evidence_detail?.length ? (
          <div className="level-review-mapped-detail">
            <ul>
              {summary.mapped_evidence_detail.map((item) => (
                <li key={item.criterion_id}>
                  <strong>{item.label}</strong>
                  <ul>
                    {item.spans.map((span) => (
                      <li key={span.coding_id} className="muted">
                        {span.text}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="level-review-actions">
          {summary?.mapped_evidence_detail?.length ? (
            <button
              type="button"
              className="link-button"
              onClick={() => setShowMappedEvidence((value) => !value)}
            >
              {showMappedEvidence ? "Hide mapped evidence" : "View mapped evidence"}
            </button>
          ) : null}
          {interpretation?.id ? (
            <button type="button" className="button-secondary" onClick={handleVerify}>
              Verify with AI
            </button>
          ) : null}
        </div>

      </div>
    </section>
  );
}
