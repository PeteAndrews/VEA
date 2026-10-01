import {
  configureStore,
  createListenerMiddleware,
  isAnyOf,
} from "@reduxjs/toolkit";
import aiReducer, { runEvidenceCheck } from "./aiSlice";
import authReducer from "./authSlice";
import assessmentsReducer from "./assessmentsSlice";
import judgementReducer, {
  createCoding,
  updateCodingCriterion,
  updateCodingSpan,
} from "./judgementSlice";
import markingReducer from "./markingSlice";

const listenerMiddleware = createListenerMiddleware();

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
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().prepend(listenerMiddleware.middleware),
});
