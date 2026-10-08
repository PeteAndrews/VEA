import { Fragment, useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { createCoding, focusCoding, updateCodingCriterion } from "../judgementSlice";
import EvidenceLinkCell from "./EvidenceLinkCell";

function evidenceLinksForCriterion(codings, criterionId) {
  return codings.filter((coding) => coding.criterion_id === criterionId);
}

export default function IndicativeContentPanel({ assessmentId, candidateId, indicativeContent }) {
  const dispatch = useDispatch();
  const { markingSessionId } = useSelector((state) => state.auth);
  const { draft, reviseCodingId, codings, focusedCodingId, pendingCriterionId, saving } =
    useSelector((state) => state.judgement);
  const [expandedCriterionId, setExpandedCriterionId] = useState(null);

  useEffect(() => {
    if (!focusedCodingId) return;
    const coding = codings.find((item) => item.id === focusedCodingId);
    if (!coding) return;
    document.getElementById(`criterion-row-${coding.criterion_id}`)?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [focusedCodingId, codings]);

  if (!indicativeContent) return null;

  const displayGroups = indicativeContent.groups.filter((group) => group.key_steps.length > 0);
  const canCode = Boolean(draft) || Boolean(reviseCodingId);

  function handleCriterionClick(criterionId) {
    if (!canCode || saving) return;

    if (reviseCodingId) {
      dispatch(
        updateCodingCriterion({
          markingSessionId,
          assessmentId,
          candidateId,
          codingId: reviseCodingId,
          criterionId,
        })
      );
      return;
    }

    if (draft) {
      dispatch(
        createCoding({
          markingSessionId,
          assessmentId,
          candidateId,
          draft,
          criterionId,
        })
      );
    }
  }

  function rowClass(criterionId) {
    const classes = [];
    if (canCode) classes.push("clickable-row");
    if (
      focusedCodingId &&
      codings.some((coding) => coding.id === focusedCodingId && coding.criterion_id === criterionId)
    ) {
      classes.push("linked-row");
    }
    return classes.join(" ");
  }

  function renderRow(criterionId, contentCell, rowClassName = "") {
    const links = evidenceLinksForCriterion(codings, criterionId);
    return (
      <div
        id={`criterion-row-${criterionId}`}
        className={`indicative-matrix-row ${rowClassName} ${rowClass(criterionId)}`.trim()}
      >
        <div
          className={`indicative-matrix-cell content-cell${
            canCode || links.length ? " criterion-target" : ""
          }`}
          onClick={() => handleCriterionClick(criterionId)}
        >
          {contentCell}
        </div>
        <div className="indicative-matrix-cell evidence-cell">
          <EvidenceLinkCell
            assessmentId={assessmentId}
            candidateId={candidateId}
            criterionId={criterionId}
            links={links}
            expanded={expandedCriterionId === criterionId}
            onToggle={(open) => setExpandedCriterionId(open ? criterionId : null)}
          />
        </div>
        <div className="indicative-matrix-cell confidence-cell">
          <span className="matrix-pill">—</span>
        </div>
      </div>
    );
  }

  return (
    <section className="panel panel-wide indicative-content-panel">
      {canCode ? (
        <header className="panel-header indicative-content-hint">
          <span className="muted">
            {reviseCodingId ? "Click a criterion to reassign" : "Click a criterion to link evidence"}
          </span>
        </header>
      ) : null}
      <div className="panel-body">
        <div className="indicative-matrix">
          <div className="indicative-matrix-columns">
            <div>Indicative content</div>
            <div>Evidence Link</div>
            <div>Confidence</div>
          </div>
          {displayGroups.map((group, groupIndex) => (
            <Fragment key={group.id}>
              {group.text ? (
                <div className={`indicative-group-header group-header-tone-${groupIndex % 4}`}>
                  {group.text.replace(/:$/, "")}
                </div>
              ) : null}
              {group.key_steps.map((step) => (
                <Fragment key={step.id}>
                  {renderRow(
                    step.id,
                    <div className="indicative-point">
                      <span className="indicative-bullet indicative-bullet-filled" aria-hidden="true" />
                      <div className="indicative-point-body">
                        <span>{step.text}</span>
                        {step.is_control_variable ? (
                          <span className="tag tag-control">Control variable</span>
                        ) : null}
                        {step.alternatives.map((alt) => (
                          <div key={alt} className="alt-line">
                            or {alt}
                          </div>
                        ))}
                      </div>
                    </div>,
                    "key-step-row"
                  )}
                  {step.details.map((detail) =>
                    renderRow(
                      detail.id,
                      <div className="indicative-point indicative-point-detail">
                        <span className="indicative-bullet indicative-bullet-hollow" aria-hidden="true" />
                        <span className="indicative-point-body">{detail.text}</span>
                      </div>,
                      "detail-row"
                    )
                  )}
                </Fragment>
              ))}
            </Fragment>
          ))}
        </div>
      </div>
    </section>
  );
}
