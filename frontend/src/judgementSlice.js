import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import {
  createCoding as apiCreateCoding,
  getJudgement,
  removeCoding as apiRemoveCoding,
  setTentativeLevel as apiSetTentativeLevel,
  updateCoding as apiUpdateCoding,
} from "./api";

function applyJudgementPayload(state, payload) {
  state.spans = payload.spans;
  state.codings = payload.codings;
  state.tentativeLevel = payload.tentative_level;
  state.levelContext = payload.level_context;
}

export const loadJudgement = createAsyncThunk(
  "judgement/load",
  async ({ markingSessionId, assessmentId, candidateId }) =>
    getJudgement(markingSessionId, assessmentId, candidateId)
);

export const createCoding = createAsyncThunk(
  "judgement/createCoding",
  async ({ markingSessionId, assessmentId, candidateId, draft, criterionId }) =>
    apiCreateCoding(markingSessionId, assessmentId, candidateId, {
      start_char: draft.start_char,
      end_char: draft.end_char,
      text: draft.text,
      criterion_id: criterionId,
    })
);

export const updateCodingCriterion = createAsyncThunk(
  "judgement/updateCodingCriterion",
  async ({ markingSessionId, assessmentId, candidateId, codingId, criterionId }) =>
    apiUpdateCoding(markingSessionId, assessmentId, candidateId, codingId, {
      criterion_id: criterionId,
    })
);

export const updateCodingSpan = createAsyncThunk(
  "judgement/updateCodingSpan",
  async ({ markingSessionId, assessmentId, candidateId, codingId, draft }) =>
    apiUpdateCoding(markingSessionId, assessmentId, candidateId, codingId, {
      start_char: draft.start_char,
      end_char: draft.end_char,
      text: draft.text,
    })
);

export const removeCoding = createAsyncThunk(
  "judgement/removeCoding",
  async ({ markingSessionId, assessmentId, candidateId, codingId }) =>
    apiRemoveCoding(markingSessionId, assessmentId, candidateId, codingId)
);

export const setTentativeLevel = createAsyncThunk(
  "judgement/setTentativeLevel",
  async ({ markingSessionId, assessmentId, candidateId, level }) =>
    apiSetTentativeLevel(markingSessionId, assessmentId, candidateId, level)
);

const judgementSlice = createSlice({
  name: "judgement",
  initialState: {
    draft: null,
    reviseCodingId: null,
    focusedCodingId: null,
    pendingCriterionId: null,
    lastAction: null,
    spans: [],
    codings: [],
    tentativeLevel: null,
    levelContext: null,
    status: "idle",
    saving: false,
    error: null,
  },
  reducers: {
    setDraft(state, action) {
      state.draft = action.payload;
      state.lastAction = "select_evidence";
    },
    clearDraft(state) {
      state.draft = null;
      state.pendingCriterionId = null;
    },
    setPendingCriterion(state, action) {
      state.pendingCriterionId = action.payload;
    },
    startRevise(state, action) {
      state.reviseCodingId = action.payload;
      state.focusedCodingId = action.payload;
      state.lastAction = "revise_coding";
    },
    cancelRevise(state) {
      state.reviseCodingId = null;
    },
    focusCoding(state, action) {
      state.focusedCodingId = action.payload;
    },
    resetJudgement(state) {
      state.draft = null;
      state.reviseCodingId = null;
      state.focusedCodingId = null;
      state.pendingCriterionId = null;
      state.lastAction = null;
      state.spans = [];
      state.codings = [];
      state.tentativeLevel = null;
      state.levelContext = null;
      state.status = "idle";
      state.saving = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadJudgement.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadJudgement.fulfilled, (state, action) => {
        state.status = "succeeded";
        applyJudgementPayload(state, action.payload);
      })
      .addCase(loadJudgement.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      });

    builder
      .addCase(createCoding.pending, (state) => {
        state.saving = true;
        state.error = null;
      })
      .addCase(createCoding.fulfilled, (state, action) => {
        state.saving = false;
        applyJudgementPayload(state, action.payload);
        state.draft = null;
        state.reviseCodingId = null;
        state.pendingCriterionId = null;
        state.lastAction = "link_evidence";
        const { criterionId, draft } = action.meta.arg;
        const coding = action.payload.codings.find(
          (item) =>
            item.criterion_id === criterionId &&
            item.start_char === draft.start_char &&
            item.end_char === draft.end_char
        );
        state.focusedCodingId = coding?.id ?? null;
      })
      .addCase(createCoding.rejected, (state, action) => {
        state.saving = false;
        state.pendingCriterionId = null;
        state.error = action.error.message;
      })
      .addCase(updateCodingCriterion.pending, (state) => {
        state.saving = true;
        state.error = null;
      })
      .addCase(updateCodingCriterion.fulfilled, (state, action) => {
        state.saving = false;
        applyJudgementPayload(state, action.payload);
        state.draft = null;
        state.reviseCodingId = null;
        state.pendingCriterionId = null;
        state.lastAction = "revise_coding";
        state.focusedCodingId = action.meta.arg.codingId;
      })
      .addCase(updateCodingCriterion.rejected, (state, action) => {
        state.saving = false;
        state.pendingCriterionId = null;
        state.error = action.error.message;
      });

    const savingCases = [updateCodingSpan, removeCoding, setTentativeLevel];
    for (const thunk of savingCases) {
      builder
        .addCase(thunk.pending, (state) => {
          state.saving = true;
          state.error = null;
        })
        .addCase(thunk.fulfilled, (state, action) => {
          state.saving = false;
          applyJudgementPayload(state, action.payload);
          if (thunk === updateCodingSpan) {
            state.draft = null;
            state.reviseCodingId = null;
            state.pendingCriterionId = null;
            state.lastAction = "revise_coding";
            state.focusedCodingId = action.meta.arg.codingId;
          }
          if (thunk === removeCoding) {
            state.lastAction = "unlink_evidence";
          }
          if (thunk === setTentativeLevel) {
            state.lastAction = "set_tentative_level";
          }
        })
        .addCase(thunk.rejected, (state, action) => {
          state.saving = false;
          state.error = action.error.message;
        });
    }
  },
});

export const {
  setDraft,
  clearDraft,
  startRevise,
  cancelRevise,
  focusCoding,
  setPendingCriterion,
  resetJudgement,
} = judgementSlice.actions;
export default judgementSlice.reducer;
