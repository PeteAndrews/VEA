import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { collapseAssistantPanel, expandAssistantPanel, sendAssistantMessage } from "../conversationSlice";

function formatTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ExaminerAssistantPanel({ assessmentId, candidateId }) {
  const dispatch = useDispatch();
  const messagesEndRef = useRef(null);
  const [draft, setDraft] = useState("");
  const { markingSessionId } = useSelector((state) => state.auth);
  const { conversation, collapsed, sendStatus, launchStatus, sendError, launchError } = useSelector(
    (state) => state.conversation
  );

  const activeContext = conversation?.active_context;
  const activeContextId = conversation?.active_context_id;
  const messages = (conversation?.messages || []).filter(
    (message) => !activeContextId || message.context_id === activeContextId
  );

  useEffect(() => {
    if (!collapsed) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [collapsed, messages.length, launchStatus, sendStatus]);

  function handleToggleCollapse() {
    if (collapsed) {
      dispatch(expandAssistantPanel());
    } else {
      dispatch(collapseAssistantPanel());
    }
  }

  function handleSend(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sendStatus === "loading" || launchStatus === "loading") return;
    setDraft("");
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
          <div className="assistant-messages">
            {launchStatus === "loading" ? (
              <p className="status-text">Launching assistant...</p>
            ) : null}
            {launchError ? <p className="error">{launchError}</p> : null}
            {!activeContext && messages.length === 0 && launchStatus !== "loading" ? (
              <p className="assistant-empty">
                Use <strong>Explore</strong> on an intervention or <strong>Verify</strong> on a linked
                evidence span to start.
              </p>
            ) : null}
            {messages.map((message) => (
              <div key={message.id} className="assistant-message-row">
                <div className={`assistant-message assistant-message-${message.role}`}>
                  <div className="assistant-message-bubble">
                    <p>{message.content}</p>
                  </div>
                  <span className="assistant-message-time">{formatTime(message.created_at)}</span>
                </div>
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
                placeholder="Ask a question..."
                disabled={!activeContext || sendStatus === "loading" || launchStatus === "loading"}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button
                type="submit"
                className="assistant-send-button"
                aria-label="Send message"
                disabled={
                  !draft.trim() ||
                  !activeContext ||
                  sendStatus === "loading" ||
                  launchStatus === "loading"
                }
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
