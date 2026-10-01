import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import {
  getCandidate,
  getIndicativeContent,
  getLevels,
  getQuestion,
} from "./api";

export const loadMarkingScreen = createAsyncThunk(
  "marking/loadScreen",
  async ({ assessmentId, candidateId }) => {
    const [question, levelsPayload, indicativeContent, selectedResponse] = await Promise.all([
      getQuestion(assessmentId),
      getLevels(assessmentId),
      getIndicativeContent(assessmentId),
      getCandidate(assessmentId, candidateId),
    ]);
    return {
      assessmentId,
      candidateId,
      question,
      levelDescriptors: levelsPayload.levels,
      errataWarnings: levelsPayload.errata_warnings,
      indicativeContent,
      selectedResponse,
    };
  }
);

const markingSlice = createSlice({
  name: "marking",
  initialState: {
    selectedAssessmentId: null,
    selectedCandidateId: null,
    question: null,
    levelDescriptors: [],
    errataWarnings: [],
    indicativeContent: null,
    selectedResponse: null,
    status: "idle",
    error: null,
  },
  reducers: {
    clearMarking(state) {
      state.selectedAssessmentId = null;
      state.selectedCandidateId = null;
      state.question = null;
      state.levelDescriptors = [];
      state.errataWarnings = [];
      state.indicativeContent = null;
      state.selectedResponse = null;
      state.status = "idle";
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadMarkingScreen.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadMarkingScreen.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.selectedAssessmentId = action.payload.assessmentId;
        state.selectedCandidateId = action.payload.candidateId;
        state.question = action.payload.question;
        state.levelDescriptors = action.payload.levelDescriptors;
        state.errataWarnings = action.payload.errataWarnings;
        state.indicativeContent = action.payload.indicativeContent;
        state.selectedResponse = action.payload.selectedResponse;
      })
      .addCase(loadMarkingScreen.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      });
  },
});

export const { clearMarking } = markingSlice.actions;
export default markingSlice.reducer;
