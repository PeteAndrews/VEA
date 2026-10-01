import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import {
  getAiInterpretations,
  runAiCheck,
  updateAiInterpretation,
} from "./api";
import { selectInteractionStage } from "./stage";

function applyInterpretation(state, interpretation) {
  state.byCodingId[interpretation.coding_id] = interpretation;
  if (interpretation.status === "pending") {
    state.activeCardId = interpretation.id;
  }
}

export const loadAiInterpretations = createAsyncThunk(
  "ai/load",
  async ({ markingSessionId, assessmentId, candidateId }) => {
    const payload = await getAiInterpretations(markingSessionId, assessmentId, candidateId);
    return payload.interpretations;
  }
);

export const runEvidenceCheck = createAsyncThunk(
  "ai/runCheck",
  async ({ markingSessionId, assessmentId, candidateId, codingId }, { getState }) => {
    const stage = selectInteractionStage(getState());
    const lastAction = getState().judgement.lastAction;
    return runAiCheck(markingSessionId, assessmentId, candidateId, codingId, {
      stage,
      last_action: lastAction,
    });
  }
);

export const setInterventionStatus = createAsyncThunk(
  "ai/setStatus",
  async ({ markingSessionId, assessmentId, candidateId, aiId, status }) =>
    updateAiInterpretation(markingSessionId, assessmentId, candidateId, aiId, status)
);

const aiSlice = createSlice({
  name: "ai",
  initialState: {
    byCodingId: {},
    checkingCodingIds: [],
    activeCardId: null,
    status: "idle",
    error: null,
  },
  reducers: {
    showInterventionCard(state, action) {
      state.activeCardId = action.payload;
    },
    clearActiveCard(state) {
      state.activeCardId = null;
    },
    resetAi(state) {
      state.byCodingId = {};
      state.checkingCodingIds = [];
      state.activeCardId = null;
      state.status = "idle";
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadAiInterpretations.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadAiInterpretations.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.byCodingId = {};
        for (const interpretation of action.payload) {
          state.byCodingId[interpretation.coding_id] = interpretation;
        }
      })
      .addCase(loadAiInterpretations.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      });

    builder
      .addCase(runEvidenceCheck.pending, (state, action) => {
        const codingId = action.meta.arg.codingId;
        if (!state.checkingCodingIds.includes(codingId)) {
          state.checkingCodingIds.push(codingId);
        }
        state.error = null;
      })
      .addCase(runEvidenceCheck.fulfilled, (state, action) => {
        const codingId = action.meta.arg.codingId;
        state.checkingCodingIds = state.checkingCodingIds.filter((id) => id !== codingId);
        applyInterpretation(state, action.payload);
      })
      .addCase(runEvidenceCheck.rejected, (state, action) => {
        const codingId = action.meta.arg.codingId;
        state.checkingCodingIds = state.checkingCodingIds.filter((id) => id !== codingId);
        state.error = action.error.message;
      });

    builder.addCase(setInterventionStatus.fulfilled, (state, action) => {
      applyInterpretation(state, action.payload);
      if (action.payload.status === "dismissed") {
        state.activeCardId = null;
      }
    });
  },
});

export const { showInterventionCard, clearActiveCard, resetAi } = aiSlice.actions;
export default aiSlice.reducer;
