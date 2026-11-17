import { useEffect, useRef, useState } from "react";
import { useDispatch } from "react-redux";
import { useNavigate, useParams } from "react-router-dom";

import AppShell from "../components/AppShell";
import { fetchQuestionnaire, saveQuestionnaireDraft, submitQuestionnaire } from "../api";
import { applyStudyProgress } from "../studySlice";

function isLikertScale(item) {
  if (item.kind !== "single" || !item.options?.length) return false;
  return item.options.every((option) => option.id === "prefer_not" || /^\d+$/.test(option.id));
}

function sliderBubbleLeft(value, min, max) {
  const ratio = max === min ? 0 : (value - min) / (max - min);
  const thumb = 16;
  return `calc(${ratio * 100}% + ${(0.5 - ratio) * thumb}px)`;
}

export default function QuestionnairePage() {
  const { key, scope } = useParams();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [form, setForm] = useState(null);
  const [answers, setAnswers] = useState({});
  const [status, setStatus] = useState("new");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const updatedAt = useRef(null);
  const skipSave = useRef(true);
  const answersRef = useRef(answers);
  answersRef.current = answers;

  useEffect(() => {
    let cancelled = false;
    skipSave.current = true;
    setForm(null);
    setError("");
    fetchQuestionnaire(key, scope)
      .then((payload) => {
        if (cancelled) return;
        updatedAt.current = payload.updated_at || null;
        setForm(payload.form);
        setAnswers(payload.answers || {});
        setStatus(payload.status || "new");
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [key, scope]);

  useEffect(() => {
    if (!form || status === "submitted") return undefined;
    if (skipSave.current) {
      skipSave.current = false;
      return undefined;
    }
    const handle = setTimeout(() => {
      saveQuestionnaireDraft(key, scope, answersRef.current, updatedAt.current)
        .then((saved) => {
          updatedAt.current = saved.updated_at || updatedAt.current;
          setError("");
        })
        .catch(async (err) => {
          if (String(err.message).includes("updated elsewhere")) {
            const fresh = await fetchQuestionnaire(key, scope);
            updatedAt.current = fresh.updated_at || null;
            skipSave.current = true;
            setAnswers(fresh.answers || {});
            setStatus(fresh.status || "new");
            setNotice("Loaded the latest saved answers");
            return;
          }
          setError(err.message);
        });
    }, 700);
    return () => clearTimeout(handle);
  }, [answers, form, key, scope, status]);

  function updateAnswer(itemId, value) {
    setNotice("");
    setAnswers((current) => ({ ...current, [itemId]: value }));
  }

  function toggleMulti(item, optionId) {
    const exclusive = new Set(item.exclusive || []);
    setNotice("");
    setAnswers((current) => {
      const selected = current[item.id] || [];
      let next;
      if (selected.includes(optionId)) {
        next = selected.filter((id) => id !== optionId);
      } else if (exclusive.has(optionId)) {
        next = [optionId];
      } else {
        next = [...selected.filter((id) => !exclusive.has(id)), optionId];
      }
      return { ...current, [item.id]: next };
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const result = await submitQuestionnaire(key, scope, answers, updatedAt.current);
      dispatch(applyStudyProgress(result.progress));
      navigate(result.progress?.next?.route || "/questions", { replace: true });
    } catch (err) {
      if (String(err.message).includes("updated elsewhere")) {
        const fresh = await fetchQuestionnaire(key, scope);
        updatedAt.current = fresh.updated_at || null;
        skipSave.current = true;
        setAnswers(fresh.answers || {});
        setStatus(fresh.status || "new");
      }
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell breadcrumb="Study > Questionnaire">
      <form className="questionnaire-page" onSubmit={handleSubmit}>
        {!form && !error ? <p>Loading questionnaire...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {form ? (
          <>
            <h1>{form.title}</h1>
            {form.introduction ? <p className="muted">{form.introduction}</p> : null}
            {(form.reminders || []).map((reminder) => (
              <p key={reminder.id} className="questionnaire-reminder">
                {reminder.text}
              </p>
            ))}
            {form.items.map((item) => (
              <fieldset key={item.id} className="questionnaire-item">
                {item.kind === "note" ? <p>{item.prompt}</p> : <legend>{item.prompt}</legend>}
                {item.definition ? <p className="muted">{item.definition}</p> : null}
                {item.kind === "single" ? (
                  <div className={isLikertScale(item) ? "questionnaire-scale" : "questionnaire-options"}>
                    {item.options.map((option) => (
                      <label key={option.id}>
                        <input
                          type="radio"
                          name={item.id}
                          checked={answers[item.id] === option.id}
                          onChange={() => updateAnswer(item.id, option.id)}
                          disabled={status === "submitted"}
                        />
                        <span>{option.label}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
                {item.kind === "multi" ? (
                  <div className="questionnaire-options">
                    {item.options.map((option) => (
                      <label key={option.id}>
                        <input
                          type="checkbox"
                          checked={(answers[item.id] || []).includes(option.id)}
                          onChange={() => toggleMulti(item, option.id)}
                          disabled={status === "submitted"}
                        />
                        {option.label}
                      </label>
                    ))}
                  </div>
                ) : null}
                {item.text_field &&
                (answers[item.id] === item.text_option ||
                  (answers[item.id] || []).includes?.(item.text_option)) ? (
                  <label className="questionnaire-text">
                    {item.text_label}
                    <input
                      value={answers[item.text_field] || ""}
                      onChange={(event) => updateAnswer(item.text_field, event.target.value)}
                      disabled={status === "submitted"}
                    />
                  </label>
                ) : null}
                {item.kind === "ticks" ? (
                  <div className="questionnaire-ticks">
                    <div className="questionnaire-slider">
                      {answers[item.id] != null ? (
                        <span
                          className="questionnaire-slider-bubble"
                          style={{
                            left: sliderBubbleLeft(answers[item.id], item.min, item.max),
                          }}
                        >
                          {answers[item.id]}
                        </span>
                      ) : null}
                      <input
                        type="range"
                        min={item.min}
                        max={item.max}
                        step={item.step}
                        value={answers[item.id] ?? Math.round((item.min + item.max) / 2)}
                        aria-valuetext={
                          answers[item.id] == null ? "Not selected" : String(answers[item.id])
                        }
                        onChange={(event) => updateAnswer(item.id, Number(event.target.value))}
                        onPointerUp={(event) =>
                          updateAnswer(item.id, Number(event.currentTarget.value))
                        }
                        disabled={status === "submitted"}
                      />
                    </div>
                    <div className="questionnaire-slider-labels">
                      <span>{item.min_label}</span>
                      <span>{item.max_label}</span>
                    </div>
                    {answers[item.id] == null ? (
                      <p className="muted">Move or click the slider to record a rating.</p>
                    ) : null}
                  </div>
                ) : null}
                {item.kind === "pair" ? (
                  <div className="questionnaire-pair">
                    <span>{item.left}</span>
                    <div className="questionnaire-pair-scale">
                      {Array.from({ length: item.positions }, (_, index) => index + 1).map((position) => (
                        <label key={position}>
                          <input
                            type="radio"
                            name={`${item.id}-pair`}
                            checked={answers[item.id] === position}
                            onChange={() => updateAnswer(item.id, position)}
                            disabled={status === "submitted"}
                          />
                        </label>
                      ))}
                    </div>
                    <span>{item.right}</span>
                  </div>
                ) : null}
                {item.kind === "text" ? (
                  <textarea
                    value={answers[item.id] || ""}
                    onChange={(event) => updateAnswer(item.id, event.target.value)}
                    disabled={status === "submitted"}
                    rows={4}
                  />
                ) : null}
              </fieldset>
            ))}
            {notice ? <p className="muted">{notice}</p> : null}
            {status !== "submitted" ? (
              <button type="submit" disabled={submitting}>
                {submitting ? "Submitting..." : "Submit questionnaire"}
              </button>
            ) : (
              <p className="status-text">This questionnaire has been submitted.</p>
            )}
          </>
        ) : null}
      </form>
    </AppShell>
  );
}
