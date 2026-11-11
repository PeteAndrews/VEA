import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";

import { submitFinalMark } from "../studySlice";

export default function FinalMarkPanel({ trialId, maximumMark, submitted, finalMark, onSubmit }) {
  const dispatch = useDispatch();
  const { status, error } = useSelector((state) => state.study);
  const [mark, setMark] = useState(finalMark ?? "");
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  if (submitted) {
    return (
      <div className="final-mark-panel submitted">
        <p>
          Final mark submitted: <strong>{finalMark}</strong>
        </p>
      </div>
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (onSubmit) {
      setSubmitting(true);
      setSubmitError(null);
      try {
        await onSubmit(Number(mark));
      } catch (err) {
        setSubmitError(err.message);
      } finally {
        setSubmitting(false);
      }
      return;
    }
    dispatch(submitFinalMark({ trialId, finalMark: Number(mark) }));
  }

  return (
    <form className="final-mark-panel" onSubmit={handleSubmit}>
      <label htmlFor="final-mark">Final mark (0–{maximumMark})</label>
      <div className="final-mark-row">
        <input
          id="final-mark"
          type="number"
          min="0"
          max={maximumMark}
          value={mark}
          onChange={(event) => setMark(event.target.value)}
        />
        <button type="submit" disabled={status === "loading" || submitting || mark === ""}>
          {status === "loading" || submitting ? "Submitting..." : "Submit mark"}
        </button>
      </div>
      {submitError || error ? <p className="error">{submitError || error}</p> : null}
    </form>
  );
}
