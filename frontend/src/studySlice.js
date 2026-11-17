import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import {
  fetchStudyQuestions,
  fetchStudySession,
  fetchTrial,
  startQuestionTrial,
  startStudySession,
  submitTrialMark,
} from "./api";

export const openStudySession = createAsyncThunk(
  "study/openStudySession",
  async ({ token }) => startStudySession(token)
);

export const restoreStudySession = createAsyncThunk("study/restoreStudySession", async () =>
  fetchStudySession()
);

export const loadStudyQuestions = createAsyncThunk("study/loadStudyQuestions", async () =>
  fetchStudyQuestions()
);

export const continueQuestion = createAsyncThunk(
  "study/continueQuestion",
  async ({ assessmentId }) => startQuestionTrial(assessmentId)
);

export const loadTrial = createAsyncThunk("study/loadTrial", async ({ trialId }) =>
  fetchTrial(trialId)
);

export const submitFinalMark = createAsyncThunk(
  "study/submitFinalMark",
  async ({ trialId, finalMark }) => submitTrialMark(trialId, finalMark)
);

const studySlice = createSlice({
  name: "study",
  initialState: {
    participant: null,
    sessionId: null,
    questions: [],
    conditions: [],
    layout: "single",
    conditionOrder: [],
    studyComplete: false,
    progress: null,
    currentTrial: null,
    submitResult: null,
    walkthrough: null,
    missingExperimentalConfig: false,
    baselineWalkthrough: null,
    status: "idle",
    error: null,
  },
  reducers: {
    resetStudy(state) {
      state.participant = null;
      state.sessionId = null;
      state.questions = [];
      state.conditions = [];
      state.layout = "single";
      state.conditionOrder = [];
      state.studyComplete = false;
      state.progress = null;
      state.currentTrial = null;
      state.submitResult = null;
      state.walkthrough = null;
      state.missingExperimentalConfig = false;
      state.baselineWalkthrough = null;
      state.status = "idle";
      state.error = null;
    },
    clearSubmitResult(state) {
      state.submitResult = null;
    },
    markWalkthroughComplete(state) {
      state.walkthrough = { ...(state.walkthrough || {}), completed: true };
    },
    applyStudyProgress(state, action) {
      state.progress = action.payload || null;
      if (action.payload && typeof action.payload.study_complete === "boolean") {
        state.studyComplete = action.payload.study_complete;
      }
    },
    markBaselineWalkthroughComplete(state) {
      if (state.baselineWalkthrough) {
        state.baselineWalkthrough = { ...state.baselineWalkthrough, completed: true };
      }
      state.conditions = state.conditions.map((block) =>
        block.condition === "baseline" && block.baseline_walkthrough
          ? {
              ...block,
              baseline_walkthrough: { ...block.baseline_walkthrough, completed: true },
            }
          : block
      );
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(openStudySession.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(openStudySession.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.sessionId = action.payload.session_id;
        state.participant = action.payload.participant;
        state.walkthrough = action.payload.walkthrough || null;
        state.progress = action.payload.progress || null;
      })
      .addCase(openStudySession.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      })
      .addCase(restoreStudySession.fulfilled, (state, action) => {
        state.sessionId = action.payload.session_id;
        state.participant = action.payload.participant;
        state.walkthrough = action.payload.walkthrough || null;
        state.progress = action.payload.progress || null;
        state.status = "succeeded";
      })
      .addCase(restoreStudySession.rejected, (state) => {
        state.sessionId = null;
        state.participant = null;
      })
      .addCase(loadStudyQuestions.fulfilled, (state, action) => {
        state.questions = action.payload.questions;
        state.conditions = action.payload.conditions || [];
        state.layout = action.payload.layout || "single";
        state.conditionOrder = action.payload.condition_order || [];
        state.studyComplete = action.payload.study_complete;
        state.progress = action.payload.progress || null;
        state.missingExperimentalConfig = Boolean(action.payload.missing_experimental_config);
        state.baselineWalkthrough = action.payload.baseline_walkthrough || null;
        if (action.payload.walkthrough) {
          state.walkthrough = action.payload.walkthrough;
        }
        state.participant = {
          ...state.participant,
          subject: action.payload.subject,
          condition: action.payload.condition,
          experience: action.payload.experience,
        };
      })
      .addCase(continueQuestion.fulfilled, (state, action) => {
        state.currentTrial = action.payload;
      })
      .addCase(loadTrial.fulfilled, (state, action) => {
        state.currentTrial = action.payload;
      })
      .addCase(submitFinalMark.fulfilled, (state, action) => {
        state.submitResult = action.payload;
        if (action.payload.next_trial) {
          state.currentTrial = action.payload.next_trial;
        } else {
          state.currentTrial = null;
        }
      });
  },
});

export const {
  resetStudy,
  clearSubmitResult,
  applyStudyProgress,
  markWalkthroughComplete,
  markBaselineWalkthroughComplete,
} = studySlice.actions;
export default studySlice.reducer;
