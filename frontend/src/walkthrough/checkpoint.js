import {
  createCoding,
  getJudgement,
  removeCoding,
  setTentativeLevel,
  updateCoding,
} from "../api";
import { store } from "../store";
import { restoreWalkthroughCheckpoint } from "./checkpointAction";
import { captureReplayCheckpoint, restoreReplayCheckpoint } from "./replay";

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function remapCodingIds(value, idMap) {
  if (Array.isArray(value)) return value.map((item) => remapCodingIds(item, idMap));
  if (!value || typeof value !== "object") return value;
  const next = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "coding_id" && typeof item === "string") next[key] = idMap.get(item) || item;
    else next[key] = remapCodingIds(item, idMap);
  }
  return next;
}

export function captureInteractionCheckpoint() {
  const state = store.getState();
  return {
    replay: captureReplayCheckpoint(),
    conversation: clone(state.conversation),
    judgement: clone(state.judgement),
    ai: clone(state.ai),
    levelAi: clone(state.levelAi),
  };
}

function sessionIds() {
  const state = store.getState();
  return {
    markingSessionId: state.auth.markingSessionId,
    assessmentId: state.marking.selectedAssessmentId,
    candidateId: state.marking.selectedCandidateId,
  };
}

async function reconcileJudgement(snapshot) {
  const ids = sessionIds();
  if (!ids.markingSessionId || !ids.assessmentId || !ids.candidateId) return null;
  const current = store.getState().judgement.codings || [];
  const snapshotCodings = snapshot.judgement.codings || [];
  const snapshotById = new Map(snapshotCodings.map((coding) => [coding.id, coding]));

  for (const coding of current) {
    const saved = snapshotById.get(coding.id);
    if (!saved) {
      await removeCoding(ids.markingSessionId, ids.assessmentId, ids.candidateId, coding.id);
      continue;
    }
    if (
      coding.start_char !== saved.start_char ||
      coding.end_char !== saved.end_char ||
      coding.text !== saved.text ||
      coding.criterion_id !== saved.criterion_id
    ) {
      await updateCoding(ids.markingSessionId, ids.assessmentId, ids.candidateId, coding.id, {
        criterion_id: saved.criterion_id,
        start_char: saved.start_char,
        end_char: saved.end_char,
        text: saved.text,
      });
    }
  }

  for (const coding of snapshotCodings) {
    if (current.some((item) => item.id === coding.id)) continue;
    await createCoding(ids.markingSessionId, ids.assessmentId, ids.candidateId, {
      criterion_id: coding.criterion_id,
      start_char: coding.start_char,
      end_char: coding.end_char,
      text: coding.text,
    });
  }

  const savedLevel = snapshot.judgement.tentativeLevel?.level ?? null;
  const currentLevel = store.getState().judgement.tentativeLevel?.level ?? null;
  if (savedLevel !== currentLevel) {
    await setTentativeLevel(ids.markingSessionId, ids.assessmentId, ids.candidateId, savedLevel);
  }

  return getJudgement(ids.markingSessionId, ids.assessmentId, ids.candidateId);
}

function codingIdMap(snapshotCodings, serverCodings) {
  const idMap = new Map();
  const used = new Set();
  for (const saved of snapshotCodings || []) {
    const match = (serverCodings || []).find(
      (coding) =>
        !used.has(coding.id) &&
        coding.criterion_id === saved.criterion_id &&
        coding.start_char === saved.start_char &&
        coding.end_char === saved.end_char
    );
    if (!match) continue;
    used.add(match.id);
    if (match.id !== saved.id) idMap.set(saved.id, match.id);
  }
  return idMap;
}

function applyCodingIdMap(checkpoint, idMap) {
  if (!idMap.size) return checkpoint;
  const swap = (codingId) => (codingId && idMap.has(codingId) ? idMap.get(codingId) : codingId);
  const judgement = remapCodingIds(checkpoint.judgement, idMap);
  judgement.codings = (checkpoint.judgement.codings || []).map((coding) => ({
    ...coding,
    id: swap(coding.id),
  }));
  judgement.focusedCodingId = swap(judgement.focusedCodingId);
  judgement.reviseCodingId = swap(judgement.reviseCodingId);

  const ai = remapCodingIds(checkpoint.ai, idMap);
  ai.byCodingId = Object.fromEntries(
    Object.entries(checkpoint.ai.byCodingId || {}).map(([codingId, interpretation]) => {
      const nextId = swap(codingId);
      return [nextId, { ...remapCodingIds(interpretation, idMap), coding_id: nextId }];
    })
  );

  const replay = remapCodingIds(checkpoint.replay, idMap);
  replay.codingIdMap = (checkpoint.replay.codingIdMap || []).map(([recorded, actual]) => [
    recorded,
    swap(actual),
  ]);
  return { ...checkpoint, judgement, ai, replay, conversation: remapCodingIds(checkpoint.conversation, idMap), levelAi: remapCodingIds(checkpoint.levelAi, idMap) };
}

export async function restoreInteractionCheckpoint(checkpoint) {
  const saved = clone(checkpoint);
  let serverJudgement = null;
  try {
    serverJudgement = await reconcileJudgement(saved);
  } catch (error) {
    console.warn("Walkthrough restart could not fully restore the marking", error);
  }

  const idMap = codingIdMap(saved.judgement.codings, serverJudgement?.codings);
  const restored = applyCodingIdMap(saved, idMap);
  if (serverJudgement) {
    restored.judgement.codings = serverJudgement.codings;
    restored.judgement.spans = serverJudgement.spans;
    restored.judgement.tentativeLevel = serverJudgement.tentative_level;
    restored.judgement.levelContext = serverJudgement.level_context;
  }
  restored.judgement.saving = false;
  restored.judgement.error = null;
  restored.judgement.status = "succeeded";
  restored.ai.checkingCodingIds = [];
  restored.levelAi.checking = false;
  restored.conversation.launchStatus = "idle";
  restored.conversation.sendStatus = "idle";
  restored.conversation.activateStatus = "idle";
  restored.conversation.openGeneralStatus = "idle";
  restored.conversation.deleteStatus = "idle";
  restored.conversation.pendingMessageId = null;

  restoreReplayCheckpoint(restored.replay);
  store.dispatch(restoreWalkthroughCheckpoint(restored));
}
