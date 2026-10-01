import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { buildHighlightPieces, selectionToOffsets, snippet } from "../responseUtils";
import { clearDraft, focusCoding, setDraft } from "../judgementSlice";
import AllEvidenceModal from "./AllEvidenceModal";

export default function StudentResponsePanel({ response }) {
  const dispatch = useDispatch();
  const containerRef = useRef(null);
  const { draft, spans, codings, focusedCodingId, pendingCriterionId } = useSelector(
    (state) => state.judgement
  );
  const [showAllEvidence, setShowAllEvidence] = useState(false);

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        dispatch(clearDraft());
        setShowAllEvidence(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dispatch]);

  useEffect(() => {
    if (!focusedCodingId) return;
    const coding = codings.find((item) => item.id === focusedCodingId);
    if (!coding) return;
    const target = containerRef.current?.querySelector(
      `[data-start="${coding.start_char}"][data-end="${coding.end_char}"]`
    );
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusedCodingId, codings]);

  if (!response) return null;

  const pieces = buildHighlightPieces(
    response.text,
    spans,
    codings,
    draft,
    focusedCodingId
  );

  function handleMouseUp() {
    const container = containerRef.current;
    const selection = window.getSelection();
    const offsets = selectionToOffsets(container, selection, response.text);
    if (!offsets) return;
    dispatch(setDraft(offsets));
    selection.removeAllRanges();
  }

  function handlePieceClick(codingIds) {
    if (!codingIds.length) return;
    dispatch(focusCoding(codingIds[0]));
    const coding = codings.find((item) => item.id === codingIds[0]);
    if (coding) {
      document.getElementById(`criterion-row-${coding.criterion_id}`)?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
    }
  }

  function tooltipForPiece(codingIds) {
    if (!codingIds.length) return undefined;
    return codings
      .filter((coding) => codingIds.includes(coding.id))
      .map((coding) => coding.criterion_text)
      .join("; ");
  }

  return (
    <section className="panel">
      <header className="panel-header">
        <h2>Student Response</h2>
        <div className="panel-header-actions">
          {codings.length ? (
            <button
              type="button"
              className="link-button"
              onClick={() => setShowAllEvidence(true)}
            >
              View all evidence ({codings.length})
            </button>
          ) : null}
          <span className="muted">{response.word_count} words</span>
        </div>
      </header>
      <div
        ref={containerRef}
        className="panel-body response-body selectable-response"
        onMouseUp={handleMouseUp}
      >
        {pieces.map((piece, index) => {
          const classNames = ["response-piece"];
          if (piece.isDraft) classNames.push("draft");
          if (piece.isDraftPending) classNames.push("draft-pending");
          if (piece.codingIds.length) classNames.push("coded");
          if (piece.isFocused) classNames.push("focused");

          return (
            <span
              key={`${piece.start_char}-${piece.end_char}-${index}`}
              className={classNames.join(" ")}
              data-start={piece.start_char}
              data-end={piece.end_char}
              title={tooltipForPiece(piece.codingIds)}
              onClick={() => handlePieceClick(piece.codingIds)}
            >
              {piece.text}
            </span>
          );
        })}
      </div>
      {draft ? (
        <div className="draft-hint">
          <span>
            Selected: &ldquo;{snippet(draft.text)}&rdquo; — click a criterion to link ·{" "}
            <button type="button" className="link-button" onClick={() => dispatch(clearDraft())}>
              Cancel
            </button>
          </span>
        </div>
      ) : null}
      <AllEvidenceModal open={showAllEvidence} onClose={() => setShowAllEvidence(false)} />
    </section>
  );
}
