// Walkthrough copy and sequence.
// Edit the `instruction` strings in this file to change what participants read.
// Each interaction starts with phase "start" and, except the final mark, ends
// with phase "end". The Start and Complete buttons move between those cards.

export const CRIT = {
  hormones: "ms_05_6-contraception-hormones",
  contraFsh: "ms_05_6-contraception-fsh",
  contraLh: "ms_05_6-contraception-lh",
  infertFsh: "ms_05_6-infertility-fsh-detail",
  infertLh: "ms_05_6-infertility-lh-detail",
  implantation: "ms_05_6-infertility-progesterone-detail",
};

export const SPANS = {
  hormones: {
    start: 0,
    end: 61,
    text: "The contraceptive pill can contain oestrogen and progesterone",
  },
  fshShort: { start: 63, end: 80, text: "These inhibit FSH" },
  fshExpanded: {
    start: 63,
    end: 148,
    text: "These inhibit FSH, so eggs do not mature and there is no mature egg to be fertilised.",
  },
  lhInhibition: {
    start: 149,
    end: 236,
    text: "They also inhibit LH, preventing ovulation, so an egg is not released for fertilisation",
  },
  infertFsh: {
    start: 239,
    end: 315,
    text: "For infertility, FSH can be given to stimulate eggs to mature in the ovaries",
  },
  lhOvulation: {
    start: 317,
    end: 398,
    text: "LH can then stimulate ovulation, increasing the chance of an egg being fertilised",
  },
  ivf: {
    start: 400,
    end: 499,
    text: "In IVF, eggs are collected and fertilised outside the body, and an embryo is placed into the uterus",
  },
  progesterone: {
    start: 501,
    end: 604,
    text: "Progesterone can be given to maintain the uterus lining, increasing the chance of the embryo implanting",
  },
};

// How close a highlight must be before it is accepted and snapped to the
// practice sentence. Raise a value to be stricter, lower it to be looser.
const MIN_SPAN_COVERAGE = 0.5;
const MIN_LENGTH_RATIO = 0.45;
const MAX_LENGTH_RATIO = 1.8;

const PRESCRIBED_QUESTION = "Does this answer contain evidence for LH stimulating ovulation?";

const EVIDENCE_CARD = ".intervention-card:not(.level-intervention-card)";

function normalise(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .replace(/[.,;:]+$/g, "")
    .trim()
    .toLowerCase();
}

export function selectionMatches(draftText, span) {
  return normalise(draftText) === normalise(span.text);
}

export function selectionCloseEnough(draft, span) {
  if (!draft?.text || !span) return false;
  if (selectionMatches(draft.text, span.text)) return true;

  const spanLen = span.end - span.start;
  const draftLen = Number.isFinite(draft.end_char) ? draft.end_char - draft.start_char : draft.text.length;
  if (spanLen > 0 && Number.isFinite(draft.start_char) && Number.isFinite(draft.end_char)) {
    const overlap = Math.max(0, Math.min(draft.end_char, span.end) - Math.max(draft.start_char, span.start));
    const coverage = overlap / spanLen;
    const ratio = draftLen / spanLen;
    if (coverage >= MIN_SPAN_COVERAGE && ratio >= MIN_LENGTH_RATIO && ratio <= MAX_LENGTH_RATIO) {
      return true;
    }
  }

  const selected = normalise(draft.text);
  const target = normalise(span.text);
  const shorter = Math.min(selected.length, target.length);
  const longer = Math.max(selected.length, target.length);
  if (!longer || shorter / longer < MIN_LENGTH_RATIO) return false;
  return selected.includes(target) || target.includes(selected);
}

export function selectionReady(draft, span) {
  return draft?.start_char === span.start && draft?.end_char === span.end;
}

function link(state, span, criterionId) {
  return state.judgement.codings.find(
    (coding) =>
      coding.criterion_id === criterionId &&
      coding.start_char === span.start &&
      coding.end_char === span.end
  );
}

function hasLink(state, span, criterionId) {
  return Boolean(link(state, span, criterionId));
}

function contexts(state) {
  return state.conversation.conversation?.contexts || [];
}

function activeContext(state) {
  const conversation = state.conversation.conversation;
  return contexts(state).find((item) => item.context_id === conversation?.active_context_id);
}

function row(criterionId) {
  return `#criterion-row-${criterionId}`;
}

function intro(id, interaction, title, instruction, target = ".selectable-response") {
  return {
    id,
    interaction,
    title,
    phase: "start",
    instruction,
    target,
    allow: [],
    done: "continue",
  };
}

function summary(id, interaction, title, instruction, target) {
  return {
    id,
    interaction,
    title,
    phase: "end",
    instruction,
    target,
    allow: [],
    done: "continue",
  };
}

export const WALKTHROUGH_STEPS = [
  intro(
    "01.start",
    1,
    "Evidence linking",
    "This interaction shows how to link a sentence in the student response to a mark-scheme criterion."
  ),
  {
    id: "01.1",
    interaction: 1,
    title: "Evidence linking",
    instruction:
      "Highlight this text in the student response: “The contraceptive pill can contain oestrogen and progesterone”.",
    select: SPANS.hormones,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.hormones),
  },
  {
    id: "01.2",
    interaction: 1,
    title: "Evidence linking",
    instruction: "Select the hormone criterion: use of hormones oestrogen and progesterone.",
    target: row(CRIT.hormones),
    allow: [row(CRIT.hormones)],
    replay: { evidence_check: { recording: "001" } },
    done: (state, walk) => hasLink(state, SPANS.hormones, CRIT.hormones) && walk.served("001"),
  },
  summary(
    "01.end",
    1,
    "Evidence linking",
    "You have successfully linked evidence to a criterion. The evidence link column now displays the link.",
    row(CRIT.hormones)
  ),

  intro(
    "02.start",
    2,
    "Extend evidence",
    "This interaction shows what happens when the highlighted evidence is only part of the point."
  ),
  {
    id: "02.1",
    interaction: 2,
    title: "Extend evidence",
    instruction: "Highlight this text in the student response: “These inhibit FSH”.",
    select: SPANS.fshShort,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.fshShort),
  },
  {
    id: "02.2",
    interaction: 2,
    title: "Extend evidence",
    instruction: "Select the contraception FSH criterion for the text you highlighted.",
    target: row(CRIT.contraFsh),
    allow: [row(CRIT.contraFsh)],
    replay: { evidence_check: { recording: "002" } },
    done: (state, walk) => hasLink(state, SPANS.fshShort, CRIT.contraFsh) && walk.served("002"),
  },
  {
    id: "02.3",
    interaction: 2,
    title: "Extend evidence",
    instruction:
      "If the AI detects you have not selected enough evidence, it will allow you to adjust your code. Click Adjust code.",
    target: ".context-support-notice",
    allow: ["[data-walkthrough='adjust-code']"],
    done: () => Boolean(document.querySelector("[data-walkthrough='confirm-expand']")),
  },
  {
    id: "02.4",
    interaction: 2,
    title: "Extend evidence",
    instruction: "Confirm the expanded evidence selection.",
    target: ".context-support-notice",
    allow: ["[data-walkthrough='confirm-expand']", "[data-walkthrough='adjust-code']"],
    replay: { evidence_check: { recording: "003", suppress: true } },
    done: (state, walk) => hasLink(state, SPANS.fshExpanded, CRIT.contraFsh) && walk.served("003"),
  },
  summary(
    "02.end",
    2,
    "Extend evidence",
    "You expanded the link so it covers the rest of that point. The evidence link now uses the longer sentence.",
    row(CRIT.contraFsh)
  ),

  intro(
    "03.start",
    3,
    "Nuance",
    "This interaction shows a nuance the VEA can explain without changing your link."
  ),
  {
    id: "03.1",
    interaction: 3,
    title: "Nuance",
    instruction:
      "Highlight: “They also inhibit LH, preventing ovulation, so an egg is not released for fertilisation”.",
    select: SPANS.lhInhibition,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.lhInhibition),
  },
  {
    id: "03.2",
    interaction: 3,
    title: "Nuance",
    instruction: "Select the contraception LH criterion.",
    target: row(CRIT.contraLh),
    allow: [row(CRIT.contraLh)],
    replay: { evidence_check: { recording: "004" } },
    done: (state, walk) => hasLink(state, SPANS.lhInhibition, CRIT.contraLh) && walk.served("004"),
  },
  {
    id: "03.3",
    interaction: 3,
    title: "Nuance",
    instruction: "Read the nuance, then click Explore to open the VEA’s explanation.",
    target: EVIDENCE_CARD,
    allow: ["[data-walkthrough='explore']"],
    replay: { conversation_launch: { recording: "005" } },
    done: (_state, walk) => walk.served("005"),
  },
  {
    id: "03.4",
    interaction: 3,
    title: "Nuance",
    instruction: "Read the explanation in the assistant.",
    target: ".assistant-panel",
    allow: [],
    done: "continue",
    continueLabel: "Continue",
  },
  summary(
    "03.end",
    3,
    "Nuance",
    "You opened the VEA’s explanation of the nuance. The link itself stayed in place.",
    ".assistant-panel"
  ),

  intro(
    "04.start",
    4,
    "Re-anchor",
    "This interaction shows a link the VEA asks you to re-anchor. You will make it, read why, then remove it."
  ),
  {
    id: "04.1",
    interaction: 4,
    title: "Re-anchor",
    instruction:
      "Highlight: “For infertility, FSH can be given to stimulate eggs to mature in the ovaries”.",
    select: SPANS.infertFsh,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.infertFsh),
  },
  {
    id: "04.2",
    interaction: 4,
    title: "Re-anchor",
    instruction: "Link it to the contraception FSH criterion. This association is not the right one.",
    target: row(CRIT.contraFsh),
    allow: [row(CRIT.contraFsh)],
    replay: { evidence_check: { recording: "006" } },
    done: (state, walk) => hasLink(state, SPANS.infertFsh, CRIT.contraFsh) && walk.served("006"),
  },
  {
    id: "04.3",
    interaction: 4,
    title: "Re-anchor",
    instruction: "Click Explore and read why the VEA is asking you to re-anchor this link.",
    target: EVIDENCE_CARD,
    allow: ["[data-walkthrough='explore']"],
    replay: { conversation_launch: { recording: "007" } },
    done: (_state, walk) => walk.served("007"),
  },
  {
    id: "04.4",
    interaction: 4,
    title: "Re-anchor",
    instruction: "Read the explanation.",
    target: ".assistant-panel",
    allow: [],
    done: "continue",
    continueLabel: "Continue",
  },
  {
    id: "04.5",
    interaction: 4,
    title: "Re-anchor",
    instruction: "Open the contraception FSH link and unlink the infertility sentence.",
    target: [
      `${row(CRIT.contraFsh)} .evidence-popover`,
      `${row(CRIT.contraFsh)} .evidence-link-summary`,
    ],
    allow: [
      `${row(CRIT.contraFsh)} .evidence-link-summary`,
      `.evidence-popover-item[data-start='${SPANS.infertFsh.start}'] [data-walkthrough='unlink']`,
    ],
    done: (state) => !hasLink(state, SPANS.infertFsh, CRIT.contraFsh),
  },
  summary(
    "04.end",
    4,
    "Re-anchor",
    "You removed the link the VEA asked you to re-anchor. The contraception FSH link no longer includes that sentence.",
    row(CRIT.contraFsh)
  ),

  intro(
    "05.start",
    5,
    "Challenge",
    "This interaction shows a link the VEA challenges. You will make it, read why, then remove it."
  ),
  {
    id: "05.1",
    interaction: 5,
    title: "Challenge",
    instruction:
      "Highlight: “Progesterone can be given to maintain the uterus lining, increasing the chance of the embryo implanting”.",
    select: SPANS.progesterone,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.progesterone),
  },
  {
    id: "05.2",
    interaction: 5,
    title: "Challenge",
    instruction: "Link it to the infertility FSH maturation criterion. This is also not the right criterion.",
    target: row(CRIT.infertFsh),
    allow: [row(CRIT.infertFsh)],
    replay: { evidence_check: { recording: "008" } },
    done: (state, walk) => hasLink(state, SPANS.progesterone, CRIT.infertFsh) && walk.served("008"),
  },
  {
    id: "05.3",
    interaction: 5,
    title: "Challenge",
    instruction: "Click Explore to see why the VEA challenges this link.",
    target: EVIDENCE_CARD,
    allow: ["[data-walkthrough='explore']"],
    replay: { conversation_launch: { recording: "009" } },
    done: (_state, walk) => walk.served("009"),
  },
  {
    id: "05.4",
    interaction: 5,
    title: "Challenge",
    instruction: "Read the explanation.",
    target: ".assistant-panel",
    allow: [],
    done: "continue",
    continueLabel: "Continue",
  },
  {
    id: "05.5",
    interaction: 5,
    title: "Challenge",
    instruction: "Open that link and unlink it.",
    target: [
      `${row(CRIT.infertFsh)} .evidence-popover`,
      `${row(CRIT.infertFsh)} .evidence-link-summary`,
    ],
    allow: [
      `${row(CRIT.infertFsh)} .evidence-link-summary`,
      `${row(CRIT.infertFsh)} [data-walkthrough='unlink']`,
    ],
    done: (state) => !hasLink(state, SPANS.progesterone, CRIT.infertFsh),
  },
  summary(
    "05.end",
    5,
    "Challenge",
    "You removed the link the VEA challenged.",
    row(CRIT.infertFsh)
  ),

  {
    id: "06.start",
    interaction: 6,
    title: "Conversational assistant",
    phase: "start",
    instruction:
      "This interaction shows how to ask the assistant a question and follow a grounded reference back to the response.",
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    allow: [],
    done: "continue",
  },
  {
    id: "06.1",
    interaction: 6,
    title: "Conversational assistant",
    instruction: "Close each previous assistant tab using the × on the tab.",
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    emphasize: ".assistant-tab-close",
    allow: [".assistant-tab-close"],
    done: (state) => contexts(state).length === 0,
  },
  {
    id: "06.2",
    interaction: 6,
    title: "Conversational assistant",
    instruction: "Click + to open a new chat.",
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    allow: ["[aria-label='New chat']"],
    done: (state) => activeContext(state)?.source === "general",
  },
  {
    id: "06.3",
    interaction: 6,
    title: "Conversational assistant",
    instruction: `Type this question and send it: “${PRESCRIBED_QUESTION}”`,
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    allow: [".assistant-composer"],
    focus: ".assistant-composer textarea",
    replay: { conversation_message: { recording: "010" } },
    done: (_state, walk) => walk.served("010"),
  },
  {
    id: "06.4",
    interaction: 6,
    title: "Conversational assistant",
    instruction: "Click the grounded response reference to locate that evidence in the answer.",
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    allow: [".assistant-citation"],
    done: (state) => state.judgement.quotedSpan?.start_char === SPANS.lhOvulation.start,
  },
  {
    id: "06.end",
    interaction: 6,
    title: "Conversational assistant",
    phase: "end",
    instruction:
      "You asked the assistant a question and used its reference to locate the evidence in the response.",
    target: [".selectable-response", ".assistant-panel"],
    spotlight: "all",
    allow: [],
    done: "continue",
  },

  intro(
    "07.start",
    7,
    "Additional coding",
    "This interaction adds the LH ovulation evidence to the infertility criterion."
  ),
  {
    id: "07.1",
    interaction: 7,
    title: "Additional coding",
    instruction:
      "Highlight: “LH can then stimulate ovulation, increasing the chance of an egg being fertilised”.",
    select: SPANS.lhOvulation,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.lhOvulation),
  },
  {
    id: "07.2",
    interaction: 7,
    title: "Additional coding",
    instruction: "Link it to the infertility LH / IVF criterion.",
    target: row(CRIT.infertLh),
    allow: [row(CRIT.infertLh)],
    replay: { evidence_check: { recording: "011" } },
    done: (state, walk) => hasLink(state, SPANS.lhOvulation, CRIT.infertLh) && walk.served("011"),
  },
  summary(
    "07.end",
    7,
    "Additional coding",
    "You linked the LH ovulation sentence. The evidence link column now shows that link.",
    row(CRIT.infertLh)
  ),

  intro(
    "08.start",
    8,
    "Verify",
    "This interaction codes the infertility FSH point and checks it with Verify."
  ),
  {
    id: "08.1",
    interaction: 8,
    title: "Verify",
    instruction:
      "Highlight: “For infertility, FSH can be given to stimulate eggs to mature in the ovaries”.",
    select: SPANS.infertFsh,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.infertFsh),
  },
  {
    id: "08.2",
    interaction: 8,
    title: "Verify",
    instruction: "Link it to the infertility FSH maturation criterion.",
    target: row(CRIT.infertFsh),
    allow: [row(CRIT.infertFsh)],
    replay: { evidence_check: { recording: "012" } },
    done: (state, walk) => hasLink(state, SPANS.infertFsh, CRIT.infertFsh) && walk.served("012"),
  },
  {
    id: "08.3",
    interaction: 8,
    title: "Verify",
    instruction: "Open the link and click Verify with AI.",
    target: [
      `${row(CRIT.infertFsh)} .evidence-popover`,
      `${row(CRIT.infertFsh)} .evidence-link-summary`,
    ],
    allow: [
      `${row(CRIT.infertFsh)} .evidence-link-summary`,
      `${row(CRIT.infertFsh)} [data-walkthrough='verify']`,
    ],
    replay: { conversation_launch: { recording: "013" } },
    done: (_state, walk) => walk.served("013"),
  },
  summary(
    "08.end",
    8,
    "Verify",
    "You verified the infertility FSH link. The assistant now holds that explanation.",
    ".assistant-panel"
  ),

  intro(
    "09.start",
    9,
    "Remaining evidence",
    "Now let's code the remaining evidence."
  ),
  {
    id: "09.1",
    interaction: 9,
    title: "Remaining evidence",
    instruction:
      "Highlight: “In IVF, eggs are collected and fertilised outside the body, and an embryo is placed into the uterus”.",
    select: SPANS.ivf,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.ivf),
  },
  {
    id: "09.2",
    interaction: 9,
    title: "Remaining evidence",
    instruction: "Link it to the infertility LH / IVF criterion.",
    target: row(CRIT.infertLh),
    allow: [row(CRIT.infertLh)],
    replay: { evidence_check: { recording: "014", suppress: true } },
    done: (state, walk) => hasLink(state, SPANS.ivf, CRIT.infertLh) && walk.served("014"),
  },
  {
    id: "09.3",
    interaction: 9,
    title: "Remaining evidence",
    instruction:
      "Highlight: “Progesterone can be given to maintain the uterus lining, increasing the chance of the embryo implanting”.",
    select: SPANS.progesterone,
    target: ".selectable-response",
    allow: [".selectable-response"],
    done: (state) => selectionReady(state.judgement.draft, SPANS.progesterone),
  },
  {
    id: "09.4",
    interaction: 9,
    title: "Remaining evidence",
    instruction: "Link it to the implantation criterion.",
    target: row(CRIT.implantation),
    allow: [row(CRIT.implantation)],
    replay: { evidence_check: { recording: "015" } },
    done: (state, walk) => hasLink(state, SPANS.progesterone, CRIT.implantation) && walk.served("015"),
  },
  {
    id: "09.5",
    interaction: 9,
    title: "Remaining evidence",
    instruction: "Open View all evidence and look over the links you have made.",
    target: "[data-walkthrough='view-all-evidence']",
    allow: ["[data-walkthrough='view-all-evidence']"],
    done: () => Boolean(document.querySelector(".all-evidence-modal")),
  },
  {
    id: "09.6",
    interaction: 9,
    title: "Remaining evidence",
    instruction: "Review the coded evidence, then close the list.",
    target: ".all-evidence-modal",
    allow: [".all-evidence-modal"],
    done: () => !document.querySelector(".all-evidence-modal"),
  },
  summary(
    "09.end",
    9,
    "Remaining evidence",
    "We have now completed the evidence linking. Now let's assign a level.",
    ".level-card.level-2"
  ),

  intro(
    "10.start",
    10,
    "Level selection",
    "This interaction tries Level 2 and reads the VEA's challenge.",
    ".level-card.level-2"
  ),
  {
    id: "10.3",
    interaction: 10,
    title: "Level selection",
    instruction: "Select Level 2.",
    target: ".level-card.level-2",
    allow: [".level-card.level-2"],
    replay: { level_check: { recording: "016" } },
    done: (state, walk) => state.judgement.tentativeLevel?.level === 2 && walk.served("016"),
  },
  {
    id: "10.4",
    interaction: 10,
    title: "Level selection",
    instruction: "Read the challenge, then click Explore.",
    target: [".level-card.level-2", ".level-review-panel", ".assistant-panel"],
    spotlight: "all",
    allow: ["[data-walkthrough='explore-level']"],
    replay: { conversation_launch: { recording: "017" } },
    done: (_state, walk) => walk.served("017"),
  },
  {
    id: "10.5",
    interaction: 10,
    title: "Level selection",
    instruction: "Read the level guidance in the assistant and the level review.",
    target: [".level-card.level-2", ".level-review-panel", ".assistant-panel"],
    spotlight: "all",
    allow: [],
    done: "continue",
    continueLabel: "Continue",
  },
  summary(
    "10.end",
    10,
    "Level selection",
    "You selected Level 2 and read why the VEA challenges that choice.",
    ".level-review-panel"
  ),

  intro(
    "11.start",
    11,
    "Level selection",
    "This interaction tries Level 3, which fits this response more closely.",
    ".level-card.level-3"
  ),
  {
    id: "11.1",
    interaction: 11,
    title: "Level selection",
    instruction: "Select Level 3.",
    target: ".level-card.level-3",
    allow: [".level-card.level-3"],
    replay: { level_check: { recording: "018" } },
    done: (state, walk) => state.judgement.tentativeLevel?.level === 3 && walk.served("018"),
  },
  {
    id: "11.2",
    interaction: 11,
    title: "Level selection",
    instruction: "The check broadly aligns with Level 3. Read the nuance, then dismiss it.",
    target: [".level-card.level-3", ".level-review-panel", ".assistant-panel"],
    spotlight: "all",
    allow: ["[data-walkthrough='dismiss-level']", ".level-review-panel"],
    done: (state) => state.levelAi.interpretation?.status === "dismissed",
  },
  summary(
    "11.end",
    11,
    "Level selection",
    "You selected Level 3 and dismissed the remaining nuance. The review says the response broadly aligns.",
    ".level-review-panel"
  ),

  intro(
    "12.start",
    12,
    "Final mark",
    "This last interaction submits a final mark inside the Level 3 range.",
    "#final-mark"
  ),
  {
    id: "12.1",
    interaction: 12,
    title: "Final mark",
    instruction: "Enter a final mark within Level 3 and submit it.",
    target: "#final-mark",
    allow: [".final-mark-panel"],
    focus: "#final-mark",
    done: () => false,
  },
];

export const WALKTHROUGH_INTERACTION_COUNT = WALKTHROUGH_STEPS.reduce(
  (max, step) => Math.max(max, step.interaction),
  0
);
