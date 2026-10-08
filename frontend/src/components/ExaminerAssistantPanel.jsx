import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import {
  activateConversationTab,
  collapseAssistantPanel,
  deleteConversationTab,
  expandAssistantPanel,
  openGeneralChat,
  sendAssistantMessage,
} from "../conversationSlice";
import { tabLabelsForContexts } from "../conversationTabLabels";
import { focusEvidenceSpan } from "../evidenceNavigation";
import { focusCoding } from "../judgementSlice";

function formatTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function AssistantMessage({ message, onCitationClick }) {
  return (
    <div className={`assistant-message assistant-message-${message.role}`}>
      <div className="assistant-message-bubble">
        <p>{message.content}</p>
        {message.citations?.length ? (
          <ul className="assistant-citations">
            {message.citations.map((citation, index) => (
              <li key={`${citation.type}-${index}`}>
                <button type="button" className="assistant-citation" onClick={() => onCitationClick(citation)}>
                  {citation.type === "response_span"
                    ? `Response: "${citation.text?.slice(0, 60) || "span"}"`
                    : `Criterion: ${citation.text || citation.criterion_id}`}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <span className="assistant-message-time">{formatTime(message.created_at)}</span>
    </div>
  );
}

export default function ExaminerAssistantPanel({ assessmentId, candidateId }) {
  const dispatch = useDispatch();
  const messagesEndRef = useRef(null);
  const [draftsByContext, setDraftsByContext] = useState({});
  const { markingSessionId } = useSelector((state) => state.auth);
  const {
    conversation,
    collapsed,
    sendStatus,
    launchStatus,
    activateStatus,
    openGeneralStatus,
    deleteStatus,
    sendError,
    launchError,
    activateError,
    openGeneralError,
    deleteError,
  } = useSelector((state) => state.conversation);

  const contexts = conversation?.contexts || [];
  const tabLabels = tabLabelsForContexts(contexts);
  const activeContextId = conversation?.active_context_id;
  const draft = draftsByContext[activeContextId] ?? "";
  const messages = (conversation?.messages || []).filter(
    (message) => !activeContextId || message.context_id === activeContextId
  );
  const isBusy =
    sendStatus === "loading" ||
    launchStatus === "loading" ||
    activateStatus === "loading" ||
    openGeneralStatus === "loading" ||
    deleteStatus === "loading";
  const canSend = Boolean(markingSessionId && draft.trim() && !isBusy);

  useEffect(() => {
    if (!collapsed) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [collapsed, messages.length, launchStatus, sendStatus, activeContextId]);

  function handleToggleCollapse() {
    if (collapsed) {
      dispatch(expandAssistantPanel());
    } else {
      dispatch(collapseAssistantPanel());
    }
  }

  function handleCitationClick(citation) {
    if (citation.type !== "response_span") return;
    focusEvidenceSpan({
      startChar: citation.start_char,
      endChar: citation.end_char,
      dispatch,
      focusCoding,
    });
  }

  function handleSelectTab(contextId) {
    if (!markingSessionId || contextId === activeContextId || isBusy) return;
    dispatch(
      activateConversationTab({
        markingSessionId,
        assessmentId,
        candidateId,
        contextId,
      })
    );
  }

  function handleNewChat() {
    if (!markingSessionId || isBusy) return;
    dispatch(
      openGeneralChat({
        markingSessionId,
        assessmentId,
        candidateId,
      })
    );
  }

  function handleCloseTab(contextId) {
    if (!markingSessionId || isBusy) return;
    setDraftsByContext((current) => {
      const next = { ...current };
      delete next[contextId];
      return next;
    });
    dispatch(
      deleteConversationTab({
        markingSessionId,
        assessmentId,
        candidateId,
        contextId,
      })
    );
  }

  function handleDraftChange(event) {
    const value = event.target.value;
    if (!activeContextId) return;
    setDraftsByContext((current) => ({
      ...current,
      [activeContextId]: value,
    }));
  }

  function handleSend(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!canSend || !activeContextId) return;
    setDraftsByContext((current) => ({
      ...current,
      [activeContextId]: "",
    }));
    dispatch(
      sendAssistantMessage({
        markingSessionId,
        assessmentId,
        candidateId,
        content,
      })
    );
  }

  return (
    <aside className={`assistant-panel panel${collapsed ? " collapsed" : ""}`}>
      <div className="assistant-panel-header">
        <div className="assistant-panel-title">
          <span className="assistant-panel-icon" aria-hidden="true">
            ✦
          </span>
          <h2>AI Assistant</h2>
          <span className="assistant-beta-badge">Beta</span>
        </div>
        <button
          type="button"
          className="assistant-collapse-button"
          aria-label={collapsed ? "Expand assistant" : "Minimize assistant"}
          onClick={handleToggleCollapse}
        >
          {collapsed ? "▢" : "−"}
        </button>
      </div>

      {!collapsed ? (
        <>
          <div className="assistant-tabs" role="tablist" aria-label="Assistant chats">
            {contexts.map((context, index) => (
              <div
                key={context.context_id}
                className={`assistant-tab${
                  context.context_id === activeContextId ? " active" : ""
                }`}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={context.context_id === activeContextId}
                  className="assistant-tab-label"
                  disabled={isBusy}
                  onClick={() => handleSelectTab(context.context_id)}
                >
                  {tabLabels[index]}
                </button>
                <button
                  type="button"
                  className="assistant-tab-close"
                  aria-label={`Close ${tabLabels[index]}`}
                  disabled={isBusy}
                  onClick={() => handleCloseTab(context.context_id)}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="assistant-tab assistant-tab-add"
              aria-label="New chat"
              disabled={isBusy}
              onClick={handleNewChat}
            >
              +
            </button>
          </div>

          <div className="assistant-messages">
            {launchStatus === "loading" ? (
              <p className="status-text">Launching assistant...</p>
            ) : null}
            {openGeneralStatus === "loading" ? (
              <p className="status-text">Opening new chat...</p>
            ) : null}
            {sendStatus === "loading" ? <p className="status-text">Thinking...</p> : null}
            {launchError ? <p className="error">{launchError}</p> : null}
            {activateError ? <p className="error">{activateError}</p> : null}
            {openGeneralError ? <p className="error">{openGeneralError}</p> : null}
            {deleteError ? <p className="error">{deleteError}</p> : null}
            {messages.length === 0 && !isBusy ? (
              <p className="assistant-empty">
                Ask about the response, mark scheme, current links, or use <strong>Explore</strong> /{" "}
                <strong>Verify</strong> on a coded span.
              </p>
            ) : null}
            {messages.map((message) => (
              <div key={message.id} className="assistant-message-row">
                <AssistantMessage message={message} onCitationClick={handleCitationClick} />
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <form className="assistant-composer" onSubmit={handleSend}>
            {sendError ? <p className="error">{sendError}</p> : null}
            <div className="assistant-composer-row">
              <textarea
                rows={2}
                value={draft}
                placeholder="Ask about the response, mark scheme, or a link..."
                disabled={!markingSessionId || !activeContextId || isBusy}
                onChange={handleDraftChange}
              />
              <button
                type="submit"
                className="assistant-send-button"
                aria-label="Send message"
                disabled={!canSend}
              >
                ➤
              </button>
            </div>
            <p className="assistant-footnote">
              Support only — does not change codings or tentative level.
            </p>
          </form>
        </>
      ) : null}
    </aside>
  );
}
