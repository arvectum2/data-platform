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
