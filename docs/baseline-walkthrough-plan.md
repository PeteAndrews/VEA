# Baseline walkthrough — implementation plan for Cursor

## Agreed scope

Build a short spotlight tour of the existing baseline marking interface, ending with a practice mark submission. Keep it lightweight: a small ordered step list, existing panels and controls, and the existing spotlight styling. No AI, recordings, coding interactions or new tutorial framework.

For **biology** participants who have `walkthrough_required` (including within-subjects logins), both condition walkthroughs use the same fixed practice question, regardless of condition order:

- Use question `B-JUN24-84612H-05_6` for both walkthroughs.
- VEA keeps its existing `B-JUN24-84612H-05_6_response-top-mark` response and recordings.
- Baseline uses a different existing response. Default to `B-JUN24-84612H-05_6_response-low-mark`; resolve its candidate identifier from application data rather than guessing it. Do not expose the source filename or its mark-quality label to participants.
- The entire question is practice-only and must be excluded from experimental assignments in both conditions. Individual response exclusions are unnecessary.
- Configure practice materials once at **study level** (biology block in `pilot-study.json`), not per participant. Migrate the existing VEA practice lookup from `subjects.biology.walkthrough` into that shared shape so VEA and baseline read the same question id and condition-specific response ids.

**Chemistry is out of scope for now.** Leave `CHEM-*` logins with `walkthrough_required: false` and their own experimental paper unchanged. Chemistry will later get its own practice question and the same two-condition layout as biology.

### Condition order and walkthrough access

- **A walkthrough is accessible only when its own condition is unlocked** (the participant has finished the prior condition in `condition_order`, if any).
- Enforce this on the server as well as in the menu (today the VEA walkthrough button can stay clickable inside a greyed-out block in `QuestionsPage.jsx`).
- `walkthrough_required` remains a per-person flag. On within-subjects biology logins it means **both** tours are required when that person has both conditions; each tour is gated only after its condition unlocks. Legacy single-condition logins behave as today.

## Tour sequence

1. **Welcome:** Explain that this is practice and the submitted mark will not count towards the study.
2. **Question:** Spotlight the question and available marks. Next acknowledges review.
3. **Student response:** Spotlight the answer. Allow scrolling and ordinary text selection, then Next.
4. **Mark scheme:** Spotlight level descriptors and mark ranges, then indicative content as a **second step** within the same table panel. Allow scrolling, then Next.
5. **Commentary:** Spotlight the guidance panel, then Next.
6. **Enter mark:** Allow access to all reference panels and spotlight the mark field. Ask participants to enter their chosen practice mark. Accept any whole number from zero to the question's maximum; no prescribed mark or accuracy feedback.
7. **Submit:** Spotlight Submit mark. Keep the mark editable. Finish only when the practice submission succeeds, then offer Begin baseline marking.

Next means acknowledgement, not proof that someone has read the material. No timers or quizzes.

## Implementation

- Reuse the panels in `frontend/src/pages/ControlPlaceholderPage.jsx` through a small shared layout if necessary. Add a baseline practice page and route.
- Represent the sequence in a simple data array: instruction, spotlight target, allowed controls and completion condition.
- Reuse the existing spotlight styling and only extract shared behaviour where useful. `WalkthroughOverlay.jsx` currently depends on VEA replay, selection and checkpoints; **keep those dependencies out of baseline.** Baseline restart means a clean practice session from step 1, not interaction checkpoints. Avoid a broad refactor.
- Use stable target attributes. Allow scrolling and keyboard use, keep instructions clear of the target, and prevent unrelated actions during each step. During step 6, question, response, mark scheme and commentary must remain scrollable and (where applicable) selectable.
- Reuse `FinalMarkPanel`'s existing `onSubmit` callback to save practice separately from experimental trial submissions. Validate non-empty integer marks and range on both client and server.
- Start/restart creates a clean practice session. A failed submission stays retryable. Do not carry practice form state into experimental tasks.
- **Completion storage:** do not reuse the current `walkthrough_completions` table as-is; it is keyed only by `participant_id`, so one completion would satisfy both gates. Store baseline and VEA completion in separate rows keyed by **participant and condition** (e.g. `vea` vs `baseline`). Neither completion satisfies the other requirement. **Preserve existing completions during migration:** every row already in `walkthrough_completions` becomes `condition = vea`, keeping its `final_mark`, `marking_session_id`, and `completed_at` so in-progress pilots do not lose VEA walkthrough progress.
- Add baseline start/complete endpoints and replace the baseline placeholder in `QuestionsPage.jsx` with its walkthrough entry (disabled while the baseline condition is locked).
- Require each walkthrough before its corresponding **experimental** questions in that condition, enforced by the backend. Use the requested task’s condition, not participant `experience` alone. Respect condition order: baseline-first and VEA-first must both work.
- **Experimental eligibility:** today exclusion removes only the practice *response* (`response-top-mark`). This plan excludes the **whole** question from experimental assignments in both conditions. After that change, `B-JUN24-84612H-05_6` must not appear in counterbalanced lists. Current pilot biology assignments (`pilot-study-participants.json`, default `assessment_order`) still contain only that question—implementers must **report** that replacement experimental questions are needed; do not invent replacements or delete historical submissions.
- **Practice access vs experimental assignments:** walkthrough access is independent of whether experimental question lists are empty. Once the practice question is excluded, a biology participant’s experimental lists may have no items. In that state: the **first** condition in `condition_order` remains unlocked and its walkthrough (if required) stays available; **experimental** marking for that condition must report missing assignments instead of offering trials or implying completion; the **second** condition stays locked until the first condition’s experimental work is finished (all assigned experimental questions submitted). Empty experimental lists never count as “condition complete” for unlocking, and never show study complete—only a clear message that experimental questions still need to be assigned.

The VEA walkthrough keeps its recordings, evidence-linking flow, and Level 3 practice mark rule; study-level practice config does not relax that.

## Checks before handoff

- Run the complete baseline tour with pointer and keyboard, including scrolling and successful submission.
- Check invalid marks, failed submission/retry, restart and completion after login.
- Verify both condition orders: a walkthrough is accessible only when its own condition is unlocked, and completion gates are independent per condition.
- Verify the whole practice question is excluded from experimental tasks and practice marks do not affect experimental progress.
- With empty experimental lists after exclusion, confirm the first condition’s walkthrough is still available, experimental marking reports missing assignments, and the second condition stays locked.
- Regression-check the existing VEA walkthrough and normal baseline submission. Run the frontend build and relevant backend tests.

Use temporary test participants/databases; do not complete or reset real participant tokens. Preserve existing workspace changes. No walkthrough functionality is implemented by this document alone. Do not commit or push unless requested.

## Prompt to paste into Cursor

Implement `docs/baseline-walkthrough-plan.md`. Keep it lightweight and preserve existing work. Biology participants with `walkthrough_required` use the same fixed practice-only question for both condition walkthroughs, with different existing responses. A walkthrough is accessible only when its own condition is unlocked. Migrate completion storage by condition; existing rows become `vea` with marks and timestamps preserved. Exclude the whole practice question from experimental tasks; keep first-condition walkthrough available when experimental lists are empty, report missing experimental assignments, and keep the second condition locked. Test using temporary participants, report results and any configuration gaps, and do not commit or push yet.
