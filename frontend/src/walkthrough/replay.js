import { store } from "../store";

const recordingModules = import.meta.glob("./recordings/recording_*.json", { eager: true });

const RECORDINGS = Object.fromEntries(
  Object.entries(recordingModules).map(([path, module]) => {
    const number = path.match(/recording_(\d+)\.json$/)?.[1];
    return [number, module.default];
  })
);

const PRESCRIBED_QUESTION = "Does this answer contain evidence for LH stimulating ovulation?";

let active = false;
let activeStep = null;
const served = new Set();
const codingIdMap = new Map();
const interpretations = new Map();
let levelInterpretation = null;
let conversation = emptyConversation();

function emptyConversation() {
  return {
    conversation_id: "walkthrough-conv",
    marking_session_id: null,
    assessment_id: null,
    response_id: null,
    active_context_id: null,
    contexts: [],
    messages: [],
  };
}

export function activateWalkthroughReplay() {
  active = true;
  resetWalkthroughReplay();
}

export function deactivateWalkthroughReplay() {
  active = false;
  resetWalkthroughReplay();
}

export function resetWalkthroughReplay() {
  served.clear();
  codingIdMap.clear();
  interpretations.clear();
  levelInterpretation = null;
  conversation = emptyConversation();
  activeStep = null;
}

export function setWalkthroughStep(step) {
  activeStep = step;
}

export function captureReplayCheckpoint() {
  return clone({
    served: [...served],
    codingIdMap: [...codingIdMap.entries()],
    interpretations: [...interpretations.entries()],
    levelInterpretation,
    conversation,
  });
}

export function restoreReplayCheckpoint(checkpoint) {
  served.clear();
  for (const item of checkpoint.served || []) served.add(item);
  codingIdMap.clear();
  for (const [key, value] of checkpoint.codingIdMap || []) codingIdMap.set(key, value);
  interpretations.clear();
  for (const [key, value] of checkpoint.interpretations || []) interpretations.set(key, clone(value));
  levelInterpretation = checkpoint.levelInterpretation ? clone(checkpoint.levelInterpretation) : null;
  conversation = clone(checkpoint.conversation || emptyConversation());
}

export function walkthroughRuntime() {
  return {
    served(number) {
      return served.has(String(number).padStart(3, "0"));
    },
  };
}

function recording(number) {
  return RECORDINGS[String(number).padStart(3, "0")];
}

function bodyOf(options) {
  if (!options?.body) return {};
  try {
    return JSON.parse(options.body);
  } catch {
    return {};
  }
}

function rejectLive(kind) {
  throw new Error(`Walkthrough cannot run a live ${kind}.`);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function remapCodingIds(value) {
  if (Array.isArray(value)) return value.map(remapCodingIds);
  if (!value || typeof value !== "object") return value;
  const next = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "coding_id" && typeof item === "string" && codingIdMap.has(item)) {
      next[key] = codingIdMap.get(item);
    } else {
      next[key] = remapCodingIds(item);
    }
  }
  return next;
}

function refreshSummarySpans(summary) {
  if (!summary) return summary;
  const codings = store.getState().judgement.codings || [];
  const byId = new Map(codings.map((coding) => [coding.id, coding]));
  const refresh = (spans) =>
    (spans || []).flatMap((span) => {
      const coding = byId.get(span.coding_id);
      if (!coding) {
        console.warn("Walkthrough dropped an unmapped level-summary span", span.coding_id);
        return [];
      }
      return [
        {
          ...span,
          coding_id: coding.id,
          text: coding.text,
          start_char: coding.start_char,
          end_char: coding.end_char,
        },
      ];
    });
  return {
    ...summary,
    evidence_mapped: (summary.evidence_mapped || []).map((item) => ({
      ...item,
      spans: refresh(item.spans),
    })),
    mapped_evidence_detail: (summary.mapped_evidence_detail || []).map((item) => ({
      ...item,
      spans: refresh(item.spans),
    })),
  };
}

function rememberCoding(recordedId, actualId) {
  if (recordedId && actualId) codingIdMap.set(recordedId, actualId);
}

function expected(kind) {
  const spec = activeStep?.replay?.[kind];
  if (!spec) rejectLive(kind.replaceAll("_", " "));
  const captured = recording(spec.recording);
  if (!captured) rejectLive(`${kind} recording ${spec.recording}`);
  return { spec, captured };
}

function markServed(spec) {
  served.add(String(spec.recording).padStart(3, "0"));
}

function serveInterpretation(kind, path) {
  const { spec, captured } = expected(kind);
  const actualCodingId = path.match(/\/codings\/([^/]+)\/ai-check/)?.[1] || null;
  rememberCoding(captured.context?.coding_id, actualCodingId);
  let payload = remapCodingIds(clone(captured.response));
  if (actualCodingId) payload.coding_id = actualCodingId;
  if (spec.suppress) payload = { ...payload, status: "silent" };
  if (payload.summary) payload.summary = refreshSummarySpans(payload.summary);
  if (kind === "level_check") {
    if (payload.level == null && payload.summary?.level != null) {
      payload.level = payload.summary.level;
    }
    levelInterpretation = payload;
  } else if (payload.id) {
    interpretations.set(payload.id, payload);
  }
  markServed(spec);
  return payload;
}

function newId(prefix) {
  return `${prefix}-${Math.random().toString(16).slice(2, 10)}`;
}

function adoptContext(recordedContext, actualCodingId) {
  const contextId = newId("ctx");
  const context = remapCodingIds(clone(recordedContext || { source: "general" }));
  context.context_id = contextId;
  if (actualCodingId) context.coding_id = actualCodingId;
  return context;
}

function adoptMessages(recordedMessages, contextId) {
  return (recordedMessages || []).map((message) => ({
    ...clone(message),
    id: message.id || newId("msg"),
    context_id: contextId,
  }));
}

function publishConversation() {
  const snapshot = clone(conversation);
  const activeContext =
    snapshot.contexts.find((item) => item.context_id === snapshot.active_context_id) || null;
  return {
    ...snapshot,
    active_context: activeContext,
    updated_at: new Date().toISOString(),
  };
}

function handleConversation(path, options) {
  const method = (options.method || "GET").toUpperCase();
  if (method === "GET") return publishConversation();

  if (method === "POST" && path.endsWith("/conversation/contexts")) {
    const context = { context_id: newId("ctx"), source: "general" };
    conversation.contexts.push(context);
    conversation.active_context_id = context.context_id;
    return publishConversation();
  }

  if (method === "POST" && path.endsWith("/conversation/active")) {
    const { context_id: contextId } = bodyOf(options);
    if (!conversation.contexts.some((item) => item.context_id === contextId)) {
      throw new Error("That chat is not part of this walkthrough.");
    }
    conversation.active_context_id = contextId;
    return publishConversation();
  }

  if (method === "DELETE" && path.includes("/conversation/contexts/")) {
    const contextId = decodeURIComponent(path.split("/conversation/contexts/")[1]);
    conversation.contexts = conversation.contexts.filter((item) => item.context_id !== contextId);
    conversation.messages = conversation.messages.filter((item) => item.context_id !== contextId);
    if (conversation.active_context_id === contextId) {
      conversation.active_context_id = conversation.contexts.at(-1)?.context_id || null;
    }
    return publishConversation();
  }

  if (method === "POST" && path.endsWith("/conversation/launch")) {
    const { spec, captured } = expected("conversation_launch");
    const request = bodyOf(options);
    rememberCoding(captured.context?.coding_id, request.coding_id);
    const recorded = remapCodingIds(clone(captured.response));
    const context = adoptContext(recorded.active_context, request.coding_id);
    conversation.contexts.push(context);
    conversation.active_context_id = context.context_id;
    conversation.messages.push(...adoptMessages(recorded.messages, context.context_id));
    markServed(spec);
    return publishConversation();
  }

  if (method === "POST" && path.endsWith("/conversation/messages")) {
    const content = (bodyOf(options).content || "").trim();
    const contextId = conversation.active_context_id;
    if (!contextId) throw new Error("Open a new chat before sending a message.");
    if (content !== PRESCRIBED_QUESTION) {
      throw new Error(`Type exactly: ${PRESCRIBED_QUESTION}`);
    }
    const { spec, captured } = expected("conversation_message");
    const recorded = clone(captured.response);
    conversation.messages = conversation.messages.filter((item) => item.context_id !== contextId);
    conversation.messages.push(...adoptMessages(recorded.messages, contextId));
    markServed(spec);
    return publishConversation();
  }

  rejectLive("conversation request");
}

function handleInterpretations(path, options) {
  const method = (options.method || "GET").toUpperCase();
  if (method === "GET") {
    return {
      interpretations: [...interpretations.values()],
      level_interpretation: levelInterpretation,
    };
  }
  if (method === "PATCH") {
    const aiId = path.match(/\/ai-interpretations\/([^/]+)/)?.[1];
    const status = bodyOf(options).status;
    if (levelInterpretation?.id === aiId) {
      levelInterpretation = { ...levelInterpretation, status };
      return levelInterpretation;
    }
    const current = interpretations.get(aiId);
    if (!current) rejectLive("interpretation update");
    const updated = { ...current, status };
    interpretations.set(aiId, updated);
    return updated;
  }
  rejectLive("interpretation request");
}

export async function handleWalkthroughRequest(path, options = {}) {
  if (!active) return undefined;
  const method = (options.method || "GET").toUpperCase();
  if (path.includes("/ai-interpretations")) return handleInterpretations(path, options);
  if (path.includes("/codings/") && path.endsWith("/ai-check")) {
    return serveInterpretation("evidence_check", path);
  }
  if (path.endsWith("/tentative-level/ai-check")) {
    return serveInterpretation("level_check", path);
  }
  if (path.includes("/conversation")) return handleConversation(path, options);
  if (method !== "GET" && (path.includes("/ai-check") || path.includes("/conversation"))) {
    rejectLive("AI request");
  }
  return undefined;
}
