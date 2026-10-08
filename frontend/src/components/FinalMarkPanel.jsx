import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";

import { submitFinalMark } from "../studySlice";

export default function FinalMarkPanel({ trialId, maximumMark, submitted, finalMark }) {
  const dispatch = useDispatch();
  const { status, error } = useSelector((state) => state.study);
  const [mark, setMark] = useState(finalMark ?? 0);

  if (submitted) {
    return (
      <div className="final-mark-panel submitted">
        <p>
          Final mark submitted: <strong>{finalMark}</strong>
        </p>
      </div>
    );
  }

  function handleSubmit(event) {
    event.preventDefault();
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
        <button type="submit" disabled={status === "loading"}>
          {status === "loading" ? "Submitting..." : "Submit mark"}
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
    </form>
  );
}
