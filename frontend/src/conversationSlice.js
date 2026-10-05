import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import {
  getConversation,
  launchConversation,
  sendConversationMessage,
} from "./api";
import { selectInteractionStage } from "./stage";

export const loadConversation = createAsyncThunk(
  "conversation/load",
  async ({ markingSessionId, assessmentId, candidateId }) =>
    getConversation(markingSessionId, assessmentId, candidateId)
);

export const launchAssistant = createAsyncThunk(
  "conversation/launch",
  async (
    { markingSessionId, assessmentId, candidateId, source, codingId, interpretationId },
    { getState }
  ) => {
    const stage = selectInteractionStage(getState());
    const lastAction = getState().judgement.lastAction;
    return launchConversation(markingSessionId, assessmentId, candidateId, {
      source,
      coding_id: codingId,
      interpretation_id: interpretationId,
      stage,
      last_action: lastAction,
    });
  }
);

export const sendAssistantMessage = createAsyncThunk(
  "conversation/send",
  async ({ markingSessionId, assessmentId, candidateId, content }) =>
    sendConversationMessage(markingSessionId, assessmentId, candidateId, content)
);

const conversationSlice = createSlice({
  name: "conversation",
  initialState: {
    conversation: null,
    collapsed: false,
    status: "idle",
    launchStatus: "idle",
    sendStatus: "idle",
    error: null,
    launchError: null,
    sendError: null,
  },
  reducers: {
    expandAssistantPanel(state) {
      state.collapsed = false;
    },
    collapseAssistantPanel(state) {
      state.collapsed = true;
    },
    resetConversation(state) {
      state.conversation = null;
      state.collapsed = false;
      state.status = "idle";
      state.launchStatus = "idle";
      state.sendStatus = "idle";
      state.error = null;
      state.launchError = null;
      state.sendError = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadConversation.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadConversation.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.conversation = action.payload;
      })
      .addCase(loadConversation.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.error.message;
      });

    builder
      .addCase(launchAssistant.pending, (state) => {
        state.launchStatus = "loading";
        state.launchError = null;
        state.collapsed = false;
      })
      .addCase(launchAssistant.fulfilled, (state, action) => {
        state.launchStatus = "succeeded";
        state.conversation = action.payload;
        state.collapsed = false;
      })
      .addCase(launchAssistant.rejected, (state, action) => {
        state.launchStatus = "failed";
        state.launchError = action.error.message;
      });

    builder
      .addCase(sendAssistantMessage.pending, (state) => {
        state.sendStatus = "loading";
        state.sendError = null;
      })
      .addCase(sendAssistantMessage.fulfilled, (state, action) => {
        state.sendStatus = "succeeded";
        state.conversation = action.payload;
      })
      .addCase(sendAssistantMessage.rejected, (state, action) => {
        state.sendStatus = "failed";
        state.sendError = action.error.message;
      });
  },
});

export const { expandAssistantPanel, collapseAssistantPanel, resetConversation } =
  conversationSlice.actions;
export default conversationSlice.reducer;
