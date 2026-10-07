# Qwen extraction fixtures

All twelve HTML documents and their manifests are synthetic. Invented drivers,
teams, circuits and events are explicitly identified; FIA/series source metadata
is an adapter test context, not attribution of a real publication or allegation.
The manifests pin exact raw hashes and point only to local fixture files. Imports
record fixture observations and do not access their source URLs.

`development.json` contains six manually labeled cases: F1 race points, a WEC
contract, a WRC rumor, DTM opinion, an FIA investigation and a denial. These labels
support protocol/grounding tests and prompt development. They select whole source
passages and retain literal mentions, numbers and uncertainty.

`heldout.json` reserves six separate cases covering a penalty, effective date,
clearing finding, correction, embedded instruction and unrelated content. These
cases were authored separately and have not been used to tune the prompt or
validator or as fake-model accuracy tests. Keep them reserved until a real-model
evaluation with frozen settings. The split is an initial synthetic evaluation,
not an independent real-news benchmark; create a larger unseen human-labeled
dataset for production acceptance.

Mock Ollama outputs test schema rejection, evidence grounding, bounded retry,
model provenance, leases and persistence. Passing them does not establish Qwen
accuracy, prompt-injection resistance or hardware throughput. The evaluation
command and interpretation are in [the Qwen guide](../../../docs/QWEN_EXTRACTION.md).
