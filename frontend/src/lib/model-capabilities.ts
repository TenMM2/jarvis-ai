const EMBEDDING_MODEL_PREFIXES = [
  'all-minilm',
  'bge-',
  'bge_',
  'e5-',
  'e5_',
  'gte-',
  'gte_',
  'jina-embeddings',
  'nomic-bert',
  'sentence-transformers',
];

export function isEmbedOnlyModel(modelId: string): boolean {
  const name = (modelId || '').trim().toLowerCase();
  const leaf = name.slice(name.lastIndexOf('/') + 1).split(':')[0];
  return (
    leaf.includes('embed') ||
    leaf.includes('minilm') ||
    EMBEDDING_MODEL_PREFIXES.some((prefix) => leaf.startsWith(prefix))
  );
}

// Mirrors the backend's direct-cloud routing prefixes (cloud_router.py).
// Direct-cloud models (Gemini, Claude, GPT, OpenRouter, Atlas Cloud) never
// appear in /v1/models — that endpoint only lists locally installed models
// — so a selected cloud model must not be treated as "missing" just because
// it's absent from that list.
const CLOUD_MODEL_PREFIXES = [
  'gemini-',
  'claude-',
  'gpt-',
  'o1-',
  'o3-',
  'o4-',
  'chatgpt-',
  'minimax-',
  'openrouter/',
  'atlascloud/',
];

export function isDirectCloudModel(modelId: string): boolean {
  const name = (modelId || '').trim().toLowerCase();
  return CLOUD_MODEL_PREFIXES.some((prefix) => name.startsWith(prefix));
}
