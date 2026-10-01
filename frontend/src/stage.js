const ACTION_STAGE = {
  select_evidence: "EVIDENCE_MAPPING",
  link_evidence: "EVIDENCE_MAPPING",
  revise_coding: "EVIDENCE_MAPPING",
  unlink_evidence: "EVIDENCE_MAPPING",
  set_tentative_level: "LEVEL_JUDGEMENT",
  view_level_context: "LEVEL_JUDGEMENT",
  final_mark: "DECISION",
  submit: "DECISION",
};

export function selectInteractionStage(state) {
  const { lastAction, codings, tentativeLevel } = state.judgement;
  if (lastAction && ACTION_STAGE[lastAction]) {
    return ACTION_STAGE[lastAction];
  }
  if (!codings.length && !tentativeLevel) {
    return "ORIENTATION";
  }
  if (tentativeLevel) {
    return "LEVEL_JUDGEMENT";
  }
  return "EVIDENCE_MAPPING";
}
