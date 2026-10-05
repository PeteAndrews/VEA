import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { collapseAssistantPanel, expandAssistantPanel, sendAssistantMessage } from "../conversationSlice";
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
  const canSend = Boolean(markingSessionId && draft.trim() && sendStatus !== "loading" && launchStatus !== "loading");

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

  function handleCitationClick(citation) {
    if (citation.type !== "response_span") return;
    focusEvidenceSpan({
      startChar: citation.start_char,
      endChar: citation.end_char,
      dispatch,
      focusCoding,
    });
  }

  function handleSend(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!canSend) return;
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
            {sendStatus === "loading" ? <p className="status-text">Thinking...</p> : null}
            {launchError ? <p className="error">{launchError}</p> : null}
            {messages.length === 0 && launchStatus !== "loading" && sendStatus !== "loading" ? (
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
                disabled={!markingSessionId || sendStatus === "loading" || launchStatus === "loading"}
                onChange={(event) => setDraft(event.target.value)}
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
