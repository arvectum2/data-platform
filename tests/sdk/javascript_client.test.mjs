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
