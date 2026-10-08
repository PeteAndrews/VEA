async function fetchJson(path, options = {}) {
  const response = await fetch(path, { credentials: "include", ...options });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function sendJson(method, path, body) {
  return fetchJson(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function getAssessments() {
  return fetchJson("/api/assessments");
}

export function getCandidates(assessmentId) {
  return fetchJson(`/api/assessments/${assessmentId}/candidates`);
}

export function getQuestion(assessmentId) {
  return fetchJson(`/api/assessments/${assessmentId}/question`);
}

export function getLevels(assessmentId) {
  return fetchJson(`/api/assessments/${assessmentId}/levels`);
}

export function getIndicativeContent(assessmentId) {
  return fetchJson(`/api/assessments/${assessmentId}/indicative-content`);
}

export function getCandidate(assessmentId, candidateId) {
  return fetchJson(`/api/assessments/${assessmentId}/candidates/${candidateId}`);
}

export function createMarkingSession(examinerId, label) {
  return sendJson("POST", "/api/marking-sessions", { examiner_id: examinerId, label });
}

export function getJudgement(markingSessionId, assessmentId, candidateId) {
  return fetchJson(
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement`
  );
}

export function createCoding(markingSessionId, assessmentId, candidateId, payload) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/codings`,
    payload
  );
}

export function updateCoding(markingSessionId, assessmentId, candidateId, codingId, payload) {
  return sendJson(
    "PATCH",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/codings/${codingId}`,
    payload
  );
}

export function removeCoding(markingSessionId, assessmentId, candidateId, codingId) {
  return sendJson(
    "DELETE",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/codings/${codingId}`
  );
}

export function setTentativeLevel(markingSessionId, assessmentId, candidateId, level) {
  return sendJson(
    "PUT",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/tentative-level`,
    { level }
  );
}

export function getLevelContext(assessmentId, level, markingSessionId, candidateId) {
  const params = new URLSearchParams({
    marking_session_id: markingSessionId,
    candidate_id: candidateId,
  });
  return fetchJson(`/api/assessments/${assessmentId}/levels/${level}/context?${params.toString()}`);
}

export function getAiInterpretations(markingSessionId, assessmentId, candidateId) {
  return fetchJson(
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/ai-interpretations`
  );
}

export function runAiCheck(markingSessionId, assessmentId, candidateId, codingId, payload) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/codings/${codingId}/ai-check`,
    payload
  );
}

export function runLevelAiCheck(markingSessionId, assessmentId, candidateId, payload) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/judgement/tentative-level/ai-check`,
    payload
  );
}

export function updateAiInterpretation(markingSessionId, assessmentId, candidateId, aiId, status) {
  return sendJson(
    "PATCH",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/ai-interpretations/${aiId}`,
    { status }
  );
}

export function getConversation(markingSessionId, assessmentId, candidateId) {
  return fetchJson(
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation`
  );
}

export function launchConversation(markingSessionId, assessmentId, candidateId, payload) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation/launch`,
    payload
  );
}

export function sendConversationMessage(markingSessionId, assessmentId, candidateId, content) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation/messages`,
    { content }
  );
}

export function activateConversationContext(markingSessionId, assessmentId, candidateId, contextId) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation/active`,
    { context_id: contextId }
  );
}

export function openGeneralConversationContext(markingSessionId, assessmentId, candidateId) {
  return sendJson(
    "POST",
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation/contexts`
  );
}

export function deleteConversationContext(markingSessionId, assessmentId, candidateId, contextId) {
  return fetchJson(
    `/api/marking-sessions/${markingSessionId}/assessments/${assessmentId}/candidates/${candidateId}/conversation/contexts/${encodeURIComponent(contextId)}`,
    { method: "DELETE" }
  );
}

export function startStudySession(token) {
  return sendJson("POST", "/api/study/session", { token });
}

export function fetchStudySession() {
  return fetchJson("/api/study/session");
}

export function fetchStudyQuestions() {
  return fetchJson("/api/study/questions");
}

export function startQuestionTrial(assessmentId) {
  return sendJson("POST", `/api/study/questions/${assessmentId}/next-trial`);
}

export function fetchTrial(trialId) {
  return fetchJson(`/api/study/trials/${trialId}`);
}

export function submitTrialMark(trialId, finalMark) {
  return sendJson("POST", `/api/study/trials/${trialId}/submit`, { final_mark: finalMark });
}
