import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import {
  activateConversationContext,
  deleteConversationContext,
  getConversation,
  launchConversation,
  openGeneralConversationContext,
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

export const activateConversationTab = createAsyncThunk(
  "conversation/activate",
  async ({ markingSessionId, assessmentId, candidateId, contextId }) =>
    activateConversationContext(markingSessionId, assessmentId, candidateId, contextId)
);

export const openGeneralChat = createAsyncThunk(
  "conversation/openGeneral",
  async ({ markingSessionId, assessmentId, candidateId }) =>
    openGeneralConversationContext(markingSessionId, assessmentId, candidateId)
);

export const deleteConversationTab = createAsyncThunk(
  "conversation/delete",
  async ({ markingSessionId, assessmentId, candidateId, contextId }) =>
    deleteConversationContext(markingSessionId, assessmentId, candidateId, contextId)
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
    activateStatus: "idle",
    openGeneralStatus: "idle",
    pendingMessageId: null,
    error: null,
    launchError: null,
    sendError: null,
    activateError: null,
    openGeneralError: null,
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
      state.activateStatus = "idle";
      state.openGeneralStatus = "idle";
      state.deleteStatus = "idle";
      state.pendingMessageId = null;
      state.error = null;
      state.launchError = null;
      state.sendError = null;
      state.activateError = null;
      state.openGeneralError = null;
      state.deleteError = null;
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
      .addCase(activateConversationTab.pending, (state) => {
        state.activateStatus = "loading";
        state.activateError = null;
      })
      .addCase(activateConversationTab.fulfilled, (state, action) => {
        state.activateStatus = "succeeded";
        state.conversation = action.payload;
        state.collapsed = false;
      })
      .addCase(activateConversationTab.rejected, (state, action) => {
        state.activateStatus = "failed";
        state.activateError = action.error.message;
      });

    builder
      .addCase(openGeneralChat.pending, (state) => {
        state.openGeneralStatus = "loading";
        state.openGeneralError = null;
        state.collapsed = false;
      })
      .addCase(openGeneralChat.fulfilled, (state, action) => {
        state.openGeneralStatus = "succeeded";
        state.conversation = action.payload;
        state.collapsed = false;
      })
      .addCase(openGeneralChat.rejected, (state, action) => {
        state.openGeneralStatus = "failed";
        state.openGeneralError = action.error.message;
      });

    builder
      .addCase(deleteConversationTab.pending, (state) => {
        state.deleteStatus = "loading";
        state.deleteError = null;
      })
      .addCase(deleteConversationTab.fulfilled, (state, action) => {
        state.deleteStatus = "succeeded";
        state.conversation = action.payload;
      })
      .addCase(deleteConversationTab.rejected, (state, action) => {
        state.deleteStatus = "failed";
        state.deleteError = action.error.message;
      });

    builder
      .addCase(sendAssistantMessage.pending, (state, action) => {
        state.sendStatus = "loading";
        state.sendError = null;
        const { content } = action.meta.arg;
        if (!state.conversation) {
          return;
        }
        const pendingId = `pending-${Date.now()}`;
        state.pendingMessageId = pendingId;
        state.conversation.messages.push({
          id: pendingId,
          role: "user",
          content,
          context_id: state.conversation.active_context_id,
          created_at: new Date().toISOString(),
        });
      })
      .addCase(sendAssistantMessage.fulfilled, (state, action) => {
        state.sendStatus = "succeeded";
        state.pendingMessageId = null;
        state.conversation = action.payload;
      })
      .addCase(sendAssistantMessage.rejected, (state, action) => {
        state.sendStatus = "failed";
        state.sendError = action.error.message;
        if (state.conversation?.messages && state.pendingMessageId) {
          state.conversation.messages = state.conversation.messages.filter(
            (message) => message.id !== state.pendingMessageId
          );
        }
        state.pendingMessageId = null;
      });
  },
});

export const { expandAssistantPanel, collapseAssistantPanel, resetConversation } =
  conversationSlice.actions;
export default conversationSlice.reducer;
