import {
  configureStore,
  createListenerMiddleware,
  isAnyOf,
} from "@reduxjs/toolkit";
import aiReducer, { runEvidenceCheck } from "./aiSlice";
import authReducer from "./authSlice";
import assessmentsReducer from "./assessmentsSlice";
import conversationReducer from "./conversationSlice";
import judgementReducer, {
  createCoding,
  removeCoding,
  setTentativeLevel,
  updateCodingCriterion,
  updateCodingSpan,
} from "./judgementSlice";
import levelAiReducer, {
  clearLevelInterpretation,
  runLevelCheck,
} from "./levelAiSlice";
import markingReducer from "./markingSlice";

const listenerMiddleware = createListenerMiddleware();

listenerMiddleware.startListening({
  matcher: isAnyOf(
    setTentativeLevel.fulfilled,
    createCoding.fulfilled,
    updateCodingCriterion.fulfilled,
    updateCodingSpan.fulfilled,
    removeCoding.fulfilled
  ),
  effect: async (action, listenerApi) => {
    if (action.type === setTentativeLevel.fulfilled.type) {
      const tentativeLevel = action.payload.tentative_level;
      const { markingSessionId } = listenerApi.getState().auth;
      const { selectedAssessmentId, selectedCandidateId } = listenerApi.getState().marking;
      if (!tentativeLevel) {
        listenerApi.dispatch(clearLevelInterpretation());
        return;
      }
      if (!markingSessionId || !selectedAssessmentId || !selectedCandidateId) {
        return;
      }
      listenerApi.cancelActiveListeners();
      await listenerApi.delay(300);
      listenerApi.dispatch(
        runLevelCheck({
          markingSessionId,
          assessmentId: selectedAssessmentId,
          candidateId: selectedCandidateId,
        })
      );
      return;
    }

    const state = listenerApi.getState();
    if (!state.judgement.tentativeLevel) {
      return;
    }
    const { markingSessionId } = state.auth;
    const { selectedAssessmentId, selectedCandidateId } = state.marking;
    if (!markingSessionId || !selectedAssessmentId || !selectedCandidateId) {
      return;
    }
    listenerApi.cancelActiveListeners();
    await listenerApi.delay(500);
    listenerApi.dispatch(
      runLevelCheck({
        markingSessionId,
        assessmentId: selectedAssessmentId,
        candidateId: selectedCandidateId,
      })
    );
  },
});

listenerMiddleware.startListening({
  matcher: isAnyOf(createCoding.fulfilled, updateCodingCriterion.fulfilled, updateCodingSpan.fulfilled),
  effect: async (action, listenerApi) => {
    const state = listenerApi.getState();
    const { markingSessionId } = state.auth;
    const { selectedAssessmentId, selectedCandidateId } = state.marking;
    if (!markingSessionId || !selectedAssessmentId || !selectedCandidateId) {
      return;
    }

    let codingId = action.meta.arg.codingId;
    if (action.type === createCoding.fulfilled.type) {
      const { criterionId, draft } = action.meta.arg;
      codingId = action.payload.codings.find(
        (item) =>
          item.criterion_id === criterionId &&
          item.start_char === draft.start_char &&
          item.end_char === draft.end_char
      )?.id;
    }
    if (!codingId) return;

    listenerApi.dispatch(
      runEvidenceCheck({
        markingSessionId,
        assessmentId: selectedAssessmentId,
        candidateId: selectedCandidateId,
        codingId,
      })
    );
  },
});

export const store = configureStore({
  reducer: {
    auth: authReducer,
    assessments: assessmentsReducer,
    marking: markingReducer,
    judgement: judgementReducer,
    ai: aiReducer,
    levelAi: levelAiReducer,
    conversation: conversationReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().prepend(listenerMiddleware.middleware),
});
