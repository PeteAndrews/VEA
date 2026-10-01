import { useEffect, useRef } from "react";
import { useDispatch, useSelector } from "react-redux";
import { snippet } from "../responseUtils";
import {
  cancelRevise,
  focusCoding,
  removeCoding,
  startRevise,
} from "../judgementSlice";

export default function EvidenceLinkCell({
  assessmentId,
  candidateId,
  criterionId,
  links,
  expanded,
  onToggle,
}) {
  const dispatch = useDispatch();
  const popoverRef = useRef(null);
  const { markingSessionId } = useSelector((state) => state.auth);
  const { focusedCodingId, reviseCodingId, saving } = useSelector((state) => state.judgement);

  useEffect(() => {
    if (!expanded) return undefined;
    function handlePointerDown(event) {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        onToggle(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [expanded, onToggle]);

  if (!links.length) {
    return <span className="muted-center">—</span>;
  }

  function handleFocusEvidence(codingId) {
    dispatch(focusCoding(codingId));
    const coding = links.find((item) => item.id === codingId);
    if (coding) {
      const target = document.querySelector(
        `[data-start="${coding.start_char}"][data-end="${coding.end_char}"]`
      );
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  function handleChangeCriterion(codingId) {
    dispatch(startRevise(codingId));
    onToggle(false);
  }

  function handleUnlink(codingId) {
    dispatch(
      removeCoding({
        markingSessionId,
        assessmentId,
        candidateId,
        codingId,
      })
    );
  }

  return (
    <div className="evidence-link-cell" ref={popoverRef}>
      <button
        type="button"
        className="evidence-link-summary"
        onClick={(event) => {
          event.stopPropagation();
          const opening = !expanded;
          onToggle(opening);
          if (opening && links.length) {
            handleFocusEvidence(links[0].id);
          }
        }}
      >
        <span className="badge">[{links.length} linked]</span>
        <span className="evidence-snippet">&ldquo;{snippet(links[0].text, 40)}&rdquo;</span>
      </button>
      {expanded ? (
        <div className="evidence-popover">
          {links.map((coding) => (
            <div
              key={coding.id}
              className={`evidence-popover-item${
                focusedCodingId === coding.id ? " focused" : ""
              }${reviseCodingId === coding.id ? " revising" : ""}`}
            >
              <button
                type="button"
                className="evidence-popover-select"
                onClick={() => handleFocusEvidence(coding.id)}
              >
                &ldquo;{snippet(coding.text, 80)}&rdquo;
              </button>
              <div className="evidence-popover-actions">
                <button
                  type="button"
                  className="button-secondary"
                  disabled={saving}
                  onClick={() => handleChangeCriterion(coding.id)}
                >
                  Change criterion
                </button>
                <button
                  type="button"
                  className="button-danger"
                  disabled={saving}
                  onClick={() => handleUnlink(coding.id)}
                >
                  Unlink
                </button>
              </div>
            </div>
          ))}
          {reviseCodingId ? (
            <p className="evidence-popover-hint">
              Click another criterion row to reassign, or{" "}
              <button type="button" className="link-button" onClick={() => dispatch(cancelRevise())}>
                cancel
              </button>
              .
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
