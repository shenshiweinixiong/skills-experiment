// Generated mount snapshot from week4-officebench/{structure,cases}.json.
// Keep the week4 files as the source of truth; refresh this snapshot when they change.
export const nodes = [
  { id: "locate", skill: "officebench.locate" },
  { id: "classify", skill: "officebench.intent" },
  { id: "files", skill: "officebench.file-action" },
  { id: "sheets", skill: "officebench.sheet-action" },
  { id: "path_guard", skill: "officebench.output-path-guard" },
  { id: "semantic_guard", skill: "officebench.semantic-guard" },
  { id: "native_guard", skill: "officebench.native-score" },
  { id: "commit", skill: "officebench.commit" },
];

export const edges = [
  { from: "locate", to: "classify", type: "serial" },
  { from: "classify", to: "files", type: "condition" },
  { from: "classify", to: "sheets", type: "condition" },
  { from: "files", to: "path_guard", type: "serial" },
  { from: "sheets", to: "path_guard", type: "serial" },
  { from: "path_guard", to: "semantic_guard", type: "parallel-readonly" },
  { from: "path_guard", to: "native_guard", type: "parallel-readonly" },
  { from: "semantic_guard", to: "commit", type: "join-all" },
  { from: "native_guard", to: "commit", type: "join-all" },
];

export const cases = [
  { id: "1-3/0", kind: "rename", baseline: "needs actual no-skill run" },
  { id: "1-3/1", kind: "rename", baseline: "needs actual no-skill run" },
  { id: "1-3/2", kind: "copy", baseline: "observed no-skill failure; root output rather than data/temp.xlsx" },
  { id: "1-3/3", kind: "delete", baseline: "needs actual no-skill failure; existing matrix passed" },
  { id: "1-4/0", kind: "set_cell", baseline: "needs actual no-skill failure; existing matrix passed" },
  { id: "1-4/1", kind: "append_row", baseline: "needs actual no-skill failure; existing matrix passed" },
  { id: "1-4/2", kind: "append_row", baseline: "observed no-skill failure; existing bonus changed instead of appending" },
  { id: "1-4/3", kind: "append_row", baseline: "observed no-skill failure; value utilities lost suffix fee" },
  { id: "1-5/0", kind: "set_cell", baseline: "needs actual no-skill failure; existing matrix passed" },
  { id: "1-5/1", kind: "halve", baseline: "needs actual no-skill failure; existing matrix passed" },
  { id: "1-5/2", kind: "annual_to_daily", baseline: "needs actual no-skill run" },
  { id: "1-6/1", kind: "attendance", baseline: "no-skill runs passed; not a repair" },
  { id: "1-6/2", kind: "schedule", baseline: "no-skill scored failures: Excel time cell versus text scorer" },
  { id: "1-9/2", kind: "sum_annual", baseline: "no-skill scored failures: assumed monthly components; annual units ambiguous" },
  { id: "1-6/4", kind: "percentage_words", baseline: "scored failure: numeric percentages correct semantically; scorer accepts explicit directional text" },
  { id: "1-18/1", kind: "pdf_summary", baseline: "scored failure: no searchable invitation PDF generated" },
  { id: "1-12/0", kind: "roster_count", baseline: "scored failure: count was not written to data/answer.txt" },
  { id: "1-13/2", kind: "course_requirement", baseline: "scored failure: prerequisite decision absent from data/answer.txt" },
  { id: "1-23/0", kind: "homework_sum", baseline: "scored failure: homework total absent from data/answer.txt" },
  { id: "1-11/1", kind: "split_scores", baseline: "host-side regrade confirms outputs were put at root, not data/" },
  { id: "1-11/0", kind: "sort_scores", baseline: "host-side regrade confirms sorted workbook absent under data/" },
];
