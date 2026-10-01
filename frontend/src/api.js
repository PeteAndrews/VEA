async function fetchJson(path, options = {}) {

  const response = await fetch(path, options);

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


