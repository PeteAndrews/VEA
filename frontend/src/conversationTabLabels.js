function truncate(text, max = 18) {
  if (!text) return "";
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function tabBaseLabel(context) {
  switch (context.source) {
    case "explore":
      return "Explore";
    case "verify":
      return "Verify";
    case "explore_level":
      return "Level explore";
    case "verify_level":
      return "Level review";
    default:
      return "New chat";
  }
}

function tabQualifier(context) {
  if (context.criterion?.text) {
    return truncate(context.criterion.text);
  }
  if (context.level != null) {
    return `L${context.level}`;
  }
  return "";
}

export function tabLabelsForContexts(contexts = []) {
  const bases = contexts.map((context) => tabBaseLabel(context));
  const totalByBase = bases.reduce((counts, base) => {
    counts[base] = (counts[base] || 0) + 1;
    return counts;
  }, {});
  const seen = {};

  return contexts.map((context, index) => {
    const base = bases[index];
    seen[base] = (seen[base] || 0) + 1;
    const qualifier = tabQualifier(context);

    let label = base;
    if (totalByBase[base] > 1 && seen[base] > 1) {
      label = `${base} ${seen[base]}`;
    }
    if (qualifier) {
      label = `${label}: ${qualifier}`;
    }
    return label;
  });
}
