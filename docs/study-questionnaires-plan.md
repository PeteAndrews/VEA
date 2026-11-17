# Study questionnaires — implementation plan

Status: plan only. Preserve existing workspace changes; do not implement, commit or push as part of preparing this document.

## Agreed scope and sequence

Integrate questionnaires into the existing study interface and SQLite study database. Use fixed forms, not a survey builder or external survey service.

1. Login. There is no consent step in the app; do not build one. If the background questionnaire is not submitted, login goes there.
2. Background questionnaire, once per participant, before either condition's walkthrough or tasks.
3. First assigned condition: its walkthrough, experimental marking, then Raw NASA-TLX, SUS and full UEQ.
4. Second assigned condition: its walkthrough, experimental marking, then the same three questionnaires in the same order.
5. Final interface preference and explanation, after both conditions' questionnaires are submitted.
6. Study complete.

Use configured condition order; do not assume baseline always precedes VEA. Every participant in this study is within-subjects (`condition_order`). Legacy single-condition logins are removed from `backend/config/studies/pilot-study-participants.json` (`CHEM-VEA-001`, `CHEM-CTL-001`, `BIO-VEA-001`, `BIO-CTL-001`, `BIO-VEA-002`, `BIO-VEA-003`). Keep `BIO-001` and `BIO-002`, and leave the chemistry subject config in place for later. Do not delete existing `study.db` rows for the removed logins; removing them from the participants file stops new sessions. Do not keep a questionnaire branch for those logins.

The A/B mapping is authoritative and assigned once on the server when the participant is provisioned. Default at that moment: the first entry in `condition_order` is Interface A and the second is Interface B, unless a mapping is already stored. After that, the interface, questionnaire headings, preference options and exports all read this stored mapping. Do not recalculate it from `condition_order`, from which condition was finished first, or from questionnaire records. A copy may be written into `context_json` from that stored mapping at submit time, but nothing reads those copies back to decide labels.

The user will supply the VEA interactive-feature questionnaire later. Do not invent its items or block progress on a questionnaire that is not yet implemented. Its future insertion point is after VEA's common questionnaires and before progression. Accountability and Paas are not included.

## Background questionnaire v1 (approved wording)

Introduction: These questions help us understand participants' backgrounds and previous experience. Please do not include your name, school or other identifying details in written answers. You may choose "Prefer not to say" for any question.

1. **What is your age group?** Single choice: 18–24; 25–34; 35–44; 45–54; 55–64; 65 or over; Prefer not to say.
2. **How do you describe your gender?** Single choice: Woman; Man; Non-binary; Prefer to self-describe (optional text); Prefer not to say.
3. **Which associate role or roles do you currently hold?** Multiple choice: Associate Chief Examiner; Associate Lead Examiner; Associate Assistant Lead Examiner; Associate Examiner; Associate General Marker; Associate Reserve; Chair of Examiners; Other (optional text); Not applicable; Prefer not to say.
4. **How many years of teaching experience do you have in total?** Count completed years, including previous roles. Single choice: None; Less than 1 year; 1–2 years; 3–5 years; 6–10 years; 11–15 years; 16 years or more; Prefer not to say.
5. **In how many separate calendar years have you marked external examinations for an awarding organisation?** Count each year once, even if you marked more than one series. Exclude classroom marking and internal mock examinations. Single choice: None; 1–2 years; 3–5 years; 6–10 years; 11–15 years; 16 years or more; Prefer not to say.
6. **In which of the following years have you marked external examinations?** Multiple choice: 2026; 2025; 2024; 2023; 2022; 2021; 2020; 2019 or earlier; Not applicable — I have not marked external examinations; Prefer not to say.
7. **During the past three months, how often have you used conversational AI tools such as ChatGPT, Microsoft Copilot or Google Gemini?** Include use for work or personal purposes. Select the closest description. Single choice: Never; Less than once a month; A few times a month; About once a week; Several times a week; Daily or almost daily; Prefer not to say.
8. **I would be willing to use AI suggestions when making marking decisions.**
9. **I expect AI assistance could improve the quality of my marking decisions.**

Before items 8–9: For the following statements, AI-assisted marking means a system that provides suggestions or explanations while the human examiner retains the final marking decision.

Items 8–9 each use: 1 Strongly disagree; 2 Disagree; 3 Somewhat disagree; 4 Neither agree nor disagree; 5 Somewhat agree; 6 Agree; 7 Strongly agree; or Prefer not to say (separate nonnumeric value).

Keep all nine questions visible, including Q6's requested Not applicable option. Exclusive choices in multi-select questions clear other choices. Catch contradictory Q5=None with named marking years and let participants correct it. Do not infer answers from another question. Optional text remains optional; declining disclosure is a valid completed answer. Preserve the 2026 options in this version rather than silently changing them with the calendar.

## Post-condition questionnaires

Use original instrument wording and instructions, not reconstructed variants. Copy approved source material into a tracked reference location where redistribution permits; do not depend on a temporary local attachment at runtime. Record source and scoring references with each fixed form definition.

- **Raw NASA-TLX:** six dimensions, no pairwise comparisons; 0–100 ratings in increments of five. Preserve official anchors and performance direction (higher represents worse performance). Show the relevant definitions and explain that ratings concern the experimental marking tasks just completed, excluding practice. Do not use the previously supplied adaptation that substitutes "fatiguing" for demand. Save all six ratings; unweighted score is their mean. Reference: https://ntrs.nasa.gov/api/citations/20000021488/downloads/20000021488.pdf
- **SUS:** all ten original items, five-point response scale, official item order and scoring. Identify "this system" as the interface just used; do not rewrite each statement. Score: sum odd items minus 1 and 5 minus even items, then multiply total by 2.5. It is a 0–100 score, not a percentage. Source: John Brooke's original SUS instrument/paper; verify against the source before transcribing.
- **Full UEQ:** all 26 original English adjective pairs, seven response positions, original order and polarity. Reproduce the supplied matrix layout responsively with accessible radio groups. Add one neutral introduction: "Considering your experience completing the marking tasks using Interface [A/B], please evaluate that interface using the word pairs below." Retain standard UEQ instructions; no per-item introductions or category headings. Score six scales using the official item mapping and reverse coding, on −3 to +3. Do not create an unsupported overall average. Reference: https://www.ueq-online.org/Material/Handbook.pdf ; supplied source: UEQ_English.pdf.

All controls begin unanswered, including TLX sliders or their accessible equivalent; a displayed midpoint must never count as an answer without a selection. Preserve partial responses when moving back/forward or retrying. Display one instrument per page, with a clear current-condition label taken from the stored A/B mapping. No participant-facing scores or evaluative feedback between conditions.

Submission is complete only when the form's rules are met:

- Background: every question has an answer. "Prefer not to say" is a valid answer and counts as complete. Optional self-describe text can be empty.
- Raw NASA-TLX: all 6 ratings are selected.
- SUS: all 10 items are answered.
- UEQ: all 26 pairs are answered.

## Final preference

Prompt: "Having used both interfaces, which would you prefer to use for similar marking tasks?"

Options: Interface A; Interface B; No preference.

Follow-up: "Please briefly explain your preference (or why you have no preference)."

Include neutral interface reminders or screenshots, using the stored A/B mapping. The choice is required, including "No preference". The explanation is optional and may be empty; say that explicitly in the implementation report. Still store both fields. Save the actual preferred condition as well as the displayed choice; No preference is a distinct value. Show this form only after both conditions and all their current required questionnaires are submitted. There is no single-condition preference case.

## Database and minimal architecture

Existing persistence is `backend/app/study/store.py`, SQLite `VEA_STUDY_DB` (normally `backend/data/study.db` when launched from backend). Schema version is currently 4; inspect again before migrating. Reuse this database rather than adding another database service.

Add one `questionnaire_responses` table through the existing migration system:

- participant_id (foreign key), questionnaire_key, scope (`study`, `baseline`, `vea`), version
- answers_json, context_json (a copy of the stored interface mapping at submit time; not a source of labels)
- status (`draft` or `submitted`), started_at, updated_at, submitted_at
- unique (participant_id, questionnaire_key, scope), so there is one current response per form/scope; version is pinned on creation and checked on updates. A later instrument revision does not open a second row.

Keys: background, nasa_tlx_raw, sus, ueq, preference. No feature-questionnaire record until its definition is supplied. Save raw selected positions, not just calculated scores. Keep declined, unanswered and not-applicable values distinguishable. Derive scores with documented versioned scoring code at export; never overwrite raw answers.

Use a small fixed definition/validation module and existing study routing/service conventions. Add authenticated GET/save-draft/submit operations. Participant identity comes from the study session, never a client-supplied participant ID. Server validates permitted form, scope, prerequisites, option values, exclusive selections, length limits and version. Drafts allow missing values; submission requires the form's defined completion rules. Submission is atomic and only persisted success unlocks progression. Identical retries return success; conflicting edits after submission are rejected, not silently overwritten. Preserve existing study and walkthrough records during migration.

Save drafts on page navigation and debounced edits; show saving/saved/error state. Draft writes compare `updated_at` so an older request cannot overwrite a newer response; submission flushes pending saves. Restore drafts after refresh/login. Do not put personal answers in URLs or routine logs.

Provide a simple researcher-run JSON/CSV export using existing project conventions (no admin dashboard). Include participant ID, condition, condition order, interface mapping, instrument/version, raw answers, completion status and timestamps; submitted scores should be reproducible. Do not export login tokens. Exclude drafts from analysis export by default. Escape CSV correctly, including free text that spreadsheet software might interpret as formulas.

## Progression and enforcement

One progress function in `backend/app/study/service.py` is the source of truth for session restore, the question menu, trial start and the destination after a final mark. Today a submitted mark returns `question_selection` from `backend/app/study/trials.py`, and both marking pages navigate from that. That destination becomes the next outstanding questionnaire, not the next condition.

Marking mutations are authorized by marking session, not by study progress. The same progress check has to run on study trial routes and on judgement writes for a study trial. Hiding a menu link is not the lock.

The calculation is:

- background_complete: background successfully submitted
- marking_complete[condition]: all assigned experimental tasks complete AND nonempty valid assignments
- questionnaires_complete[condition]: TLX, SUS and UEQ submitted for that condition
- condition_complete: marking_complete AND questionnaires_complete (plus existing walkthrough requirements)
- study_complete: both conditions complete AND final preference submitted

Background incomplete locks both conditions, including practice start, direct trial routes and marking mutations. The first condition becomes accessible after background submission. The next condition's walkthrough and tasks remain locked until the previous condition's marking and questionnaires are complete. Post-condition surveys unlock only after marking for that condition, and only in order: TLX, then SUS, then UEQ. Empty experimental lists never count as a completed condition: the first condition's walkthrough stays available, its questionnaires stay locked, and the second condition stays locked.

Use structured prerequisite errors and a server-provided next destination. Refresh/restore returns participants to the first outstanding stage. Existing pages must not interpret last-mark submission as study completion or automatically enter the next condition before questionnaires. Preserve missing-assignment handling: empty lists never count as completed conditions.

Current integration points: `backend/app/study/service.py` (`_condition_locks`, study_complete calculations, start/resume and submission destinations), `backend/app/routes/study.py`, marking API guards as needed, `frontend/src/studySlice.js`, `frontend/src/api.js`, `QuestionsPage`, login/session restore, both marking pages and walkthrough routes. Do not create a separate progression framework.

For existing test accounts, missing questionnaire records mean incomplete; do not fabricate responses or delete old marks. Roll out before participant data collection. Test with temporary databases/accounts instead of consuming real participant progress.

## Implementation order and acceptance

1. Finalize static definitions and instrument transcription against source material. Add the database migration and response persistence.
2. Implement background form, draft recovery and server enforcement before both conditions. Verify this end to end first.
3. Implement TLX, SUS and UEQ with condition-scoped persistence; update last-mark navigation and next-condition locks.
4. Add final preference/explanation, final study-complete logic and exports.
5. Test both condition orders; unauthenticated/cross-participant requests; direct-route/API bypass attempts; invalid/missing answers; declined demographics; untouched sliders; incomplete TLX, SUS or UEQ submissions; optional preference explanation; failed requests and retries; duplicate submit; reload/session recovery; migration preserving prior records; empty assignments; questionnaire scoring against known examples and official mappings. Confirm A/B labels come from the stored mapping, not from questionnaire rows.
6. Browser-check keyboard navigation, matrix/scale readability, saved-state messages, the complete sequence and accurate A/B reminders. Run frontend build and focused backend tests. Report results and unresolved issues; do not claim checks not performed.

Measure questionnaire elapsed time during the pilot from saved timestamps, noting that elapsed time includes pauses and is not active response time. Do not add minimum-time gates or forced written answers to manage data quality.

## Cursor handoff

Implement this plan in stages, beginning with background questionnaire persistence and progression locks. Preserve existing work, keep the forms fixed and lightweight, verify instrument text/scoring, and use temporary test participants. Do not invent the forthcoming VEA feature questionnaire. No commit or push unless requested.
