import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { getAiInterpretations, runLevelAiCheck, updateAiInterpretation } from "./api";
import { launchAssistant } from "./conversationSlice";
import { selectInteractionStage } from "./stage";

export const loadLevelAiInterpretation = createAsyncThunk(
  "levelAi/load",
  async ({ markingSessionId, assessmentId, candidateId }) => {
    const payload = await getAiInterpretations(markingSessionId, assessmentId, candidateId);
    return payload.level_interpretation;
  }
);

export const runLevelCheck = createAsyncThunk(
  "levelAi/runCheck",
  async ({ markingSessionId, assessmentId, candidateId }, { getState }) => {
    const stage = selectInteractionStage(getState());
    const lastAction = getState().judgement.lastAction;
    return runLevelAiCheck(markingSessionId, assessmentId, candidateId, {
      stage,
      last_action: lastAction,
    });
  }
);

export const setLevelInterventionStatus = createAsyncThunk(
  "levelAi/setStatus",
  async ({ markingSessionId, assessmentId, candidateId, aiId, status }) =>
    updateAiInterpretation(markingSessionId, assessmentId, candidateId, aiId, status)
);

const levelAiSlice = createSlice({
  name: "levelAi",
  initialState: {
    interpretation: null,
    checking: false,
    activeCard: false,
    status: "idle",
    error: null,
  },
  reducers: {
    showLevelInterventionCard(state) {
      state.activeCard = true;
    },
    clearLevelInterventionCard(state) {
      state.activeCard = false;
    },
    clearLevelInterpretation(state) {
      state.interpretation = null;
      state.activeCard = false;
      state.checking = false;
      state.error = null;
    },
    resetLevelAi(state) {
      state.interpretation = null;
      state.checking = false;
      state.activeCard = false;
      state.status = "idle";
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadLevelAiInterpretation.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadLevelAiInterpretation.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.interpretation = action.payload;
        if (action.payload?.status === "pending") {
          state.activeCard = true;
        }
      })
      .addCase(loadLevelAiInterpretation.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      });

    builder
      .addCase(runLevelCheck.pending, (state) => {
        state.checking = true;
        state.error = null;
      })
      .addCase(runLevelCheck.fulfilled, (state, action) => {
        state.checking = false;
        state.interpretation = action.payload;
        if (action.payload.status === "pending") {
          state.activeCard = true;
        }
      })
      .addCase(runLevelCheck.rejected, (state, action) => {
        state.checking = false;
        state.error = action.error.message;
      });

    builder.addCase(setLevelInterventionStatus.fulfilled, (state, action) => {
      state.interpretation = action.payload;
      if (action.payload.status === "dismissed") {
        state.activeCard = false;
      }
    });

    builder.addCase(launchAssistant.fulfilled, (state, action) => {
      const context = action.payload.active_context;
      if (context?.source === "explore_level" && state.interpretation) {
        state.interpretation = { ...state.interpretation, status: "explore" };
      }
      state.activeCard = false;
    });
  },
});

export const {
  showLevelInterventionCard,
  clearLevelInterventionCard,
  clearLevelInterpretation,
  resetLevelAi,
} = levelAiSlice.actions;
export default levelAiSlice.reducer;
