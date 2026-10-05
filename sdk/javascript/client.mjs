export const CONSUMER_CONTRACT_MAJOR = 1;

export class DataPlatformError extends Error {
  constructor(message, { status = null, method = null, path = null } = {}) {
    super(message);
    this.name = "DataPlatformError";
    this.status = status;
    this.method = method;
    this.path = path;
  }
}

export class DataPlatformClient {
  constructor({
    baseUrl,
    apiKey = "",
    consumer = "",
    consumerKey = "",
    fetchImpl = globalThis.fetch,
  }) {
    const normalized = String(baseUrl || "").replace(/\/$/, "");
    if (!normalized) throw new TypeError("Data Platform base URL must not be blank");
    if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
    this.baseUrl = normalized;
    this.apiKey = apiKey;
    this.consumer = consumer;
    this.consumerKey = consumerKey;
    this.fetchImpl = fetchImpl;
  }

  headers(extra = {}) {
    const headers = { ...extra };
    if (this.apiKey) headers["X-Arvectum-Key"] = this.apiKey;
    return headers;
  }

  async raw(path, options = {}) {
    let response;
    try {
      response = await this.fetchImpl(new URL(path, this.baseUrl), {
        ...options,
        headers: this.headers(options.headers || {}),
      });
    } catch (error) {
      throw new DataPlatformError("Data Platform request failed: " + error, {
        method: options.method || "GET",
        path,
      });
    }
    if (!response.ok) {
      const body = (await response.text()).slice(0, 500);
      throw new DataPlatformError(
        "Data Platform " +
          (options.method || "GET") +
          " " +
          path +
          " returned " +
          response.status +
          ": " +
          body,
        { status: response.status, method: options.method || "GET", path },
      );
    }
    return response;
  }

  async json(path, options = {}) {
    return (await this.raw(path, options)).json();
  }

  health() {
    return this.json("/health");
  }

  contract() {
    return this.json("/v1/contract");
  }

  async requireContract(major = CONSUMER_CONTRACT_MAJOR) {
    const contract = await this.contract();
    const actual = Number.parseInt(String(contract.version || "").split(".", 1)[0], 10);
    if (!Number.isInteger(actual) || actual !== major) {
      throw new DataPlatformError(
        "Incompatible Data Platform consumer contract: required major " +
          major +
          ", server reports " +
          contract.version,
      );
    }
    return contract;
  }

  async ensureCollection(
    collectionId,
    { owner, name, defaultLanguage = "russian", accessPolicy = null },
  ) {
    const path = "/v1/collections/" + encodeURIComponent(collectionId);
    const lookup = await this.fetchImpl(new URL(path, this.baseUrl), {
      headers: this.headers(),
    });
    if (lookup.ok) return lookup.json();
    if (lookup.status !== 404) {
      const body = (await lookup.text()).slice(0, 500);
      throw new DataPlatformError(
        "Data Platform GET " + path + " returned " + lookup.status + ": " + body,
        { status: lookup.status, method: "GET", path },
      );
    }
    const payload = {
      collection_id: collectionId,
      owner,
      name,
      default_language: defaultLanguage,
    };
    if (accessPolicy) payload.access_policy = accessPolicy;
    return this.json("/v1/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  collectionStats(collectionId) {
    return this.json(
      "/v1/collections/" + encodeURIComponent(collectionId) + "/stats",
    );
  }

  async collectionExists(collectionId) {
    const path = "/v1/collections/" + encodeURIComponent(collectionId);
    let response;
    try {
      response = await this.fetchImpl(new URL(path, this.baseUrl), {
        headers: this.headers(),
      });
    } catch (error) {
      throw new DataPlatformError("Data Platform request failed: " + error, {
        method: "GET",
        path,
      });
    }
    if (response.status === 200) return true;
    if (response.status === 404) return false;
    const body = (await response.text()).slice(0, 500);
    throw new DataPlatformError(
      "Data Platform GET " + path + " returned " + response.status + ": " + body,
      { status: response.status, method: "GET", path },
    );
  }

  async processDocument({
    collectionId,
    canonicalUri,
    title,
    content,
    filename,
    contentType = "application/octet-stream",
    chunkSizeChars = 1500,
    overlapChars = 200,
    minChunkChars = 120,
    maxChars = 2000000,
  }) {
    const form = new FormData();
    form.set("collection_id", collectionId);
    form.set("title", title);
    form.set("canonical_uri", canonicalUri);
    form.set("chunk_size_chars", String(chunkSizeChars));
    form.set("overlap_chars", String(overlapChars));
    form.set("min_chunk_chars", String(minChunkChars));
    form.set("max_chars", String(maxChars));
    form.set(
      "file",
      content instanceof Blob ? content : new Blob([content], { type: contentType }),
      filename,
    );
    return this.json("/v1/process/document", { method: "POST", body: form });
  }

  async ingestDocument({
    collectionId,
    canonicalUri,
    title,
    content,
    filename,
    contentType = "application/octet-stream",
    preChunked = false,
  }) {
    const form = new FormData();
    form.set("collection_id", collectionId);
    form.set("title", title);
    form.set("canonical_uri", canonicalUri);
    form.set("pre_chunked", preChunked ? "true" : "false");
    form.set(
      "file",
      content instanceof Blob ? content : new Blob([content], { type: contentType }),
      filename,
    );
    return this.json("/v1/ingest/document", { method: "POST", body: form });
  }

  ingestUrl({ collectionId, url, title = null }) {
    return this.json("/v1/ingest/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        collection_id: collectionId,
        url,
        ...(title ? { title } : {}),
      }),
    });
  }

  search({
    query,
    collections,
    limit = 10,
    mode = "hybrid",
    lexicalWeight = 1,
    vectorWeight = 1,
    filters = {},
    queryVariants = [],
    queryVariantWeight = 0.5,
    collapseByCanonicalUri = false,
  }) {
    const headers = { "Content-Type": "application/json" };
    if (this.consumer || this.consumerKey) {
      headers["X-Arvectum-Consumer"] = this.consumer;
      headers["X-Arvectum-Consumer-Key"] = this.consumerKey;
    }
    return this.json("/v1/search", {
      method: "POST",
      headers,
      body: JSON.stringify({
        query,
        collections,
        filters,
        limit,
        mode,
        lexical_weight: lexicalWeight,
        vector_weight: vectorWeight,
        query_variants: queryVariants,
        query_variant_weight: queryVariantWeight,
        collapse_by_canonical_uri: collapseByCanonicalUri,
      }),
    });
  }

  discover({ connector, query, cursor = null, limit = 10 }) {
    return this.json("/v1/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        connector,
        query,
        limit,
        ...(cursor ? { cursor } : {}),
      }),
    });
  }

  resolveEntity({ entityType, value, aliasKind = "name", limit = 20 }) {
    return this.json("/v1/entities/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_type: entityType,
        value,
        alias_kind: aliasKind,
        limit,
      }),
    });
  }

  createEntity({ entityType, canonicalName, aliases = [], metadata = {} }) {
    return this.json("/v1/entities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_type: entityType,
        canonical_name: canonicalName,
        aliases,
        metadata,
      }),
    });
  }

  createEntityRelation({
    sourceEntityId,
    targetEntityId,
    relationType,
    sourceCollectionId = null,
    resourceId = null,
    documentId = null,
    chunkId = null,
    metadata = {},
  }) {
    return this.json("/v1/entity-relations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_entity_id: sourceEntityId,
        target_entity_id: targetEntityId,
        relation_type: relationType,
        source_collection_id: sourceCollectionId,
        resource_id: resourceId,
        document_id: documentId,
        chunk_id: chunkId,
        metadata,
      }),
    });
  }
}
