export function focusEvidenceSpan({ startChar, endChar, dispatch, focusCoding, codingId }) {
  if (codingId && dispatch && focusCoding) {
    dispatch(focusCoding(codingId));
  }
  if (startChar == null || endChar == null) {
    return;
  }
  document
    .querySelector(`[data-start="${startChar}"][data-end="${endChar}"]`)
    ?.scrollIntoView({ block: "center", behavior: "smooth" });
}
