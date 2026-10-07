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

  const keySteps = indicativeContent.groups.flatMap((group) => group.key_steps);
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
      <tr
        id={`criterion-row-${criterionId}`}
        className={`${rowClassName} ${rowClass(criterionId)}`.trim()}
      >
        <td
          className={canCode || links.length ? "criterion-target" : undefined}
          onClick={() => handleCriterionClick(criterionId)}
        >
          {contentCell}
        </td>
        <td>
          <EvidenceLinkCell
            assessmentId={assessmentId}
            candidateId={candidateId}
            criterionId={criterionId}
            links={links}
            expanded={expandedCriterionId === criterionId}
            onToggle={(open) => setExpandedCriterionId(open ? criterionId : null)}
          />
        </td>
        <td className="muted-center">—</td>
      </tr>
    );
  }

  return (
    <section className="panel panel-wide">
      <header className="panel-header">
        <h2>Indicative Content Matrix</h2>
        {canCode ? (
          <span className="muted">
            {reviseCodingId ? "Click a criterion to reassign" : "Click a criterion to link evidence"}
          </span>
        ) : null}
      </header>
      <div className="panel-body table-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>Indicative content</th>
              <th>Evidence Link</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {keySteps.map((step) => (
              <Fragment key={step.id}>
                {renderRow(
                  step.id,
                  <>
                    <strong>{step.text}</strong>
                    {step.is_control_variable ? (
                      <span className="tag tag-control">Control variable</span>
                    ) : null}
                    {step.alternatives.map((alt) => (
                      <div key={alt} className="alt-line">
                        or {alt}
                      </div>
                    ))}
                  </>,
                  "key-step-row"
                )}
                {step.details.map((detail) =>
                  renderRow(detail.id, detail.text, "detail-row")
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
