import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { getAssessments, getCandidates } from "./api";

export const fetchAssessments = createAsyncThunk("assessments/fetchAll", async () => {
  const payload = await getAssessments();
  return payload.assessments;
});

export const fetchCandidates = createAsyncThunk(
  "assessments/fetchCandidates",
  async (assessmentId) => {
    const payload = await getCandidates(assessmentId);
    return { assessmentId, candidates: payload.candidates };
  }
);

const assessmentsSlice = createSlice({
  name: "assessments",
  initialState: {
    items: [],
    candidatesByAssessment: {},
    status: "idle",
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchAssessments.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(fetchAssessments.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.items = action.payload;
      })
      .addCase(fetchAssessments.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      })
      .addCase(fetchCandidates.fulfilled, (state, action) => {
        state.candidatesByAssessment[action.payload.assessmentId] = action.payload.candidates;
      });
  },
});

export default assessmentsSlice.reducer;
