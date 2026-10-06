import assert from "node:assert/strict";
import test from "node:test";

import {
  DataPlatformClient,
  DataPlatformError,
} from "../../sdk/javascript/client.mjs";

test("contract compatibility", async () => {
  const fetchImpl = async (url, options = {}) => {
    assert.equal(new URL(url).pathname, "/v1/contract");
    assert.equal(options.headers["X-Arvectum-Key"], "secret");
    return new Response(
      JSON.stringify({
        name: "arvectum-data-consumer",
        version: "1.0",
        api_prefix: "/v1",
        capabilities: ["search"],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    apiKey: "secret",
    fetchImpl,
  });
  const contract = await client.requireContract(1);
  assert.equal(contract.version, "1.0");
});

test("search sends consumer identity and canonical payload", async () => {
  const fetchImpl = async (url, options = {}) => {
    assert.equal(new URL(url).pathname, "/v1/search");
    assert.equal(options.headers["X-Arvectum-Consumer"], "growth-agent");
    assert.equal(options.headers["X-Arvectum-Consumer-Key"], "consumer-secret");
    const payload = JSON.parse(options.body);
    assert.equal(payload.query, "кабель");
    assert.deepEqual(payload.collections, ["growth:products"]);
    assert.equal(payload.vector_weight, 4);
    return new Response(JSON.stringify({ query: "кабель", hits: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    consumer: "growth-agent",
    consumerKey: "consumer-secret",
    fetchImpl,
  });
  const payload = await client.search({
    query: "кабель",
    collections: ["growth:products"],
    vectorWeight: 4,
  });
  assert.deepEqual(payload.hits, []);
});

test("errors expose HTTP context", async () => {
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    fetchImpl: async () => new Response("unavailable", { status: 503 }),
  });
  await assert.rejects(
    client.collectionStats("growth:products"),
    (error) =>
      error instanceof DataPlatformError &&
      error.status === 503 &&
      error.method === "GET",
  );
});

test("collectionExists distinguishes 200 and 404", async () => {
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    fetchImpl: async (url) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/present")) return new Response("{}", { status: 200 });
      if (path.endsWith("/missing")) return new Response("{}", { status: 404 });
      return new Response("unexpected", { status: 500 });
    },
  });
  assert.equal(await client.collectionExists("present"), true);
  assert.equal(await client.collectionExists("missing"), false);
});

test("processDocument uses the canonical multipart processing contract", async () => {
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    fetchImpl: async (url, options = {}) => {
      assert.equal(new URL(url).pathname, "/v1/process/document");
      assert.equal(options.method, "POST");
      assert.ok(options.body instanceof FormData);
      assert.equal(options.body.get("collection_id"), "growth:processing");
      assert.equal(options.body.get("canonical_uri"), "test://document");
      assert.equal(options.body.get("chunk_size_chars"), "1000");
      assert.equal(options.body.get("overlap_chars"), "100");
      assert.equal(options.body.get("min_chunk_chars"), "20");
      assert.equal(options.body.get("max_chars"), "50000");
      const file = options.body.get("file");
      assert.equal(file.name, "sample.txt");
      return new Response(
        JSON.stringify({
          resource_id: "resource-1",
          document_id: "doc-1",
          collection_id: "growth:processing",
          canonical_uri: "test://document",
          title: "sample",
          media_type: "text/plain",
          extraction_status: "extracted",
          text: "hello",
          chunks: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    },
  });

  const result = await client.processDocument({
    collectionId: "growth:processing",
    canonicalUri: "test://document",
    title: "sample",
    content: "hello",
    filename: "sample.txt",
    contentType: "text/plain",
    chunkSizeChars: 1000,
    overlapChars: 100,
    minChunkChars: 20,
    maxChars: 50000,
  });
  assert.equal(result.extraction_status, "extracted");
});

test("collection naming helper composes neutral namespaces", async () => {
  const { buildCollectionId } = await import("../../sdk/javascript/client.mjs");
  assert.equal(buildCollectionId("domain", "scope", "rev1"), "domain:scope:rev1");
  assert.throws(() => buildCollectionId("domain", "bad:scope"), TypeError);
});

test("searchWithProfile forwards the consumer-owned ranking profile", async () => {
  const fetchImpl = async (url, options = {}) => {
    assert.equal(new URL(url).pathname, "/v1/search");
    const payload = JSON.parse(options.body);
    assert.equal(payload.mode, "hybrid");
    assert.equal(payload.lexical_weight, 1);
    assert.equal(payload.vector_weight, 4);
    assert.equal(payload.query_variant_weight, 0.7);
    assert.equal(payload.collapse_by_canonical_uri, true);
    assert.equal(payload.rerank_strategy, "cross_encoder");
    return new Response(JSON.stringify({ query: "q", hits: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    fetchImpl,
  });
  const payload = await client.searchWithProfile({
    query: "q",
    collections: ["domain:scope:rev1"],
    profile: {
      mode: "hybrid",
      lexicalWeight: 1,
      vectorWeight: 4,
      queryVariantWeight: 0.7,
      collapseByCanonicalUri: true,
    },
  });
  assert.deepEqual(payload.hits, []);
});


test("writeMemory sends authenticated evidence-backed memory payload", async () => {
  const fetchImpl = async (url, options = {}) => {
    assert.equal(new URL(url).pathname, "/v1/memory");
    assert.equal(options.headers["X-Arvectum-Consumer"], "tender-agent");
    assert.equal(options.headers["X-Arvectum-Consumer-Key"], "secret");
    const payload = JSON.parse(options.body);
    assert.equal(payload.kind, "agent_observation");
    assert.deepEqual(payload.source_chunk_ids, ["chunk-1"]);
    assert.equal(payload.subject_key, "tender:42");
    return new Response(JSON.stringify({ record_id: "memory:1" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    consumer: "tender-agent",
    consumerKey: "secret",
    fetchImpl,
  });
  const result = await client.writeMemory({
    collectionId: "memory:shared",
    text: "Observation",
    kind: "agent_observation",
    sourceChunkIds: ["chunk-1"],
    subjectKey: "tender:42",
  });
  assert.equal(result.record_id, "memory:1");
});


test("connector credential lifecycle uses consumer auth", async () => {
  const calls = [];
  const client = new DataPlatformClient({
    baseUrl: "http://data-platform.test",
    consumer: "growth-agent",
    consumerKey: "consumer-secret",
    fetchImpl: async (url, options = {}) => {
      const path = new URL(url).pathname;
      calls.push([options.method || "GET", path]);
      assert.equal(options.headers["X-Arvectum-Consumer"], "growth-agent");
      assert.equal(options.headers["X-Arvectum-Consumer-Key"], "consumer-secret");
      if (path === "/v1/connectors/credentials" && options.method === "POST") {
        const payload = JSON.parse(options.body);
        assert.equal(payload.connector, "private-search");
        assert.deepEqual(payload.secrets, { api_key: "secret" });
        return new Response(
          JSON.stringify({
            credential_id: "cred-1",
            tenant_id: "tenant-1",
            consumer_id: "growth-agent",
            connector: "private-search",
            status: "active",
            metadata: {},
            created_at: "2026-10-06T00:00:00Z",
            revoked_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (path === "/v1/connectors/credentials" && !options.method) {
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (path === "/v1/discover") {
        const payload = JSON.parse(options.body);
        assert.equal(payload.credential_id, "cred-1");
        return new Response(
          JSON.stringify({ resources: [], next_cursor: null, warnings: [] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (path === "/v1/research") {
        const payload = JSON.parse(options.body);
        assert.equal(payload.connector, "private-search");
        assert.equal(payload.credential_id, "cred-1");
        assert.equal(payload.collection_id, "research:private");
        return new Response(
          JSON.stringify({
            query: "supplier",
            answer: null,
            claims: [],
            contradictions: [],
            uncertainty: "disabled",
            abstained: true,
            sources: [],
            evidence: [],
            warnings: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error("unexpected path " + path);
    },
  });

  const created = await client.createConnectorCredential({
    connector: "private-search",
    secrets: { api_key: "secret" },
  });
  assert.equal(created.credential_id, "cred-1");
  assert.deepEqual(await client.listConnectorCredentials(), []);
  assert.deepEqual(
    (await client.discover({
      connector: "private-search",
      query: "supplier",
      credentialId: "cred-1",
    })).resources,
    [],
  );
  const research = await client.research({
    query: "supplier",
    collectionId: "research:private",
    connector: "private-search",
    credentialId: "cred-1",
    executionMode: "research",
  });
  assert.equal(research.abstained, true);
  assert.deepEqual(calls, [
    ["POST", "/v1/connectors/credentials"],
    ["GET", "/v1/connectors/credentials"],
    ["POST", "/v1/discover"],
    ["POST", "/v1/research"],
  ]);
});
