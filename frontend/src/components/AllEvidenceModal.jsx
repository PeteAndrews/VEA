import { useDispatch, useSelector } from "react-redux";
import { snippet } from "../responseUtils";
import { focusCoding } from "../judgementSlice";

export default function AllEvidenceModal({ open, onClose }) {
  const dispatch = useDispatch();
  const { codings } = useSelector((state) => state.judgement);

  if (!open || !codings.length) return null;

  function handleFocus(coding) {
    dispatch(focusCoding(coding.id));
    document.getElementById(`criterion-row-${coding.criterion_id}`)?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
    document
      .querySelector(`[data-start="${coding.start_char}"][data-end="${coding.end_char}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  return (
    <div className="all-evidence-backdrop" onClick={onClose}>
      <div className="all-evidence-modal" onClick={(event) => event.stopPropagation()}>
        <header className="all-evidence-header">
          <h3>All linked evidence ({codings.length})</h3>
          <button type="button" className="button-secondary" onClick={onClose}>
            Close
          </button>
        </header>
        <ul className="all-evidence-list">
          {codings.map((coding) => (
            <li key={coding.id}>
              <button type="button" className="all-evidence-item" onClick={() => handleFocus(coding)}>
                <span className="all-evidence-text">&ldquo;{snippet(coding.text, 64)}&rdquo;</span>
                <span className="all-evidence-arrow">→</span>
                <span className="all-evidence-criterion">{coding.criterion_text}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
