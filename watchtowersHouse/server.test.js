import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createServer as createHttpServer, request as httpRequest } from "node:http";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createFrontendServer } from "./server.mjs";

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

function close(server) {
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

function send(port, {
  path,
  host = "dwatchtower.johnmgrubbs.io",
  headers = {},
  method = "GET",
  chunks = [],
}) {
  return new Promise((resolve, reject) => {
    const req = httpRequest({
      host: "127.0.0.1",
      port,
      path,
      method,
      headers: { ...headers, Host: host },
    }, (res) => {
      const responseChunks = [];
      res.on("data", (chunk) => responseChunks.push(chunk));
      res.on("end", () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body: Buffer.concat(responseChunks).toString("utf8"),
      }));
    });
    req.on("error", reject);
    for (const chunk of chunks) req.write(chunk);
    req.end();
  });
}

function get(port, path, host, headers) {
  return send(port, { path, host, headers });
}

function requestExpectingAbort(port, path) {
  return new Promise((resolve) => {
    const req = httpRequest({
      host: "127.0.0.1",
      port,
      path,
      headers: { Host: "dwatchtower.johnmgrubbs.io" },
    }, (res) => {
      res.on("data", () => {});
      res.once("aborted", resolve);
      res.once("error", resolve);
      res.once("end", resolve);
    });
    req.once("error", resolve);
    req.end();
  });
}

describe("production frontend server", () => {
  let api;
  let apiPort;
  let frontend;
  let frontendPort;
  let distDir;
  let lastApiHeaders;
  let apiRequestCount = 0;

  beforeAll(async () => {
    distDir = await mkdtemp(join(tmpdir(), "watchtower-frontend-"));
    await mkdir(join(distDir, "assets"));
    await writeFile(join(distDir, "index.html"), "<main>Watchtower shell</main>");
    await writeFile(join(distDir, "favicon.svg"), "<svg></svg>");
    await writeFile(join(distDir, "assets", "app-ABCDEFGH.js"), "console.log('watchtower');");
    await writeFile(join(distDir, "assets", "app.js"), "console.log('stable');");

    api = createHttpServer((req, res) => {
      apiRequestCount += 1;
      lastApiHeaders = req.headers;
      if (req.url === "/api/v1/reset") {
        res.writeHead(200, { "Content-Type": "text/plain" });
        res.write("partial");
        setImmediate(() => res.destroy(new Error("simulated upstream reset")));
        return;
      }
      res.writeHead(200, {
        "Content-Type": "application/json",
        "X-Request-ID": "test-request",
        Connection: "x-remove-response",
        "X-Remove-Response": "secret",
        "Proxy-Authenticate": "Basic realm=test",
      });
      res.end(JSON.stringify({ path: req.url }));
    });
    apiPort = await listen(api);
    frontend = createFrontendServer({
      apiOrigin: `http://127.0.0.1:${apiPort}`,
      distDir,
      maxRequestBodyBytes: 64,
    });
    frontendPort = await listen(frontend);
  });

  afterAll(async () => {
    await close(frontend);
    await close(api);
    await rm(distDir, { recursive: true, force: true });
  });

  it("serves the SPA with restrictive browser security headers", async () => {
    const response = await get(frontendPort, "/services");

    expect(response.status).toBe(200);
    expect(response.body).toContain("Watchtower shell");
    expect(response.headers["content-security-policy"]).toContain("connect-src 'self'");
    expect(response.headers["content-security-policy"]).not.toContain("ws:");
    expect(response.headers["x-frame-options"]).toBe("DENY");
    expect(response.headers["x-content-type-options"]).toBe("nosniff");
    expect(response.headers["referrer-policy"]).toBe("no-referrer");
    expect(response.headers["permissions-policy"]).toBe("camera=(), geolocation=(), microphone=()");
  });

  it("validates exact Host authority syntax", async () => {
    expect((await get(frontendPort, "/", "attacker.example")).status).toBe(403);
    expect((await get(frontendPort, "/", "[::1]attacker.example")).status).toBe(403);
    expect((await get(frontendPort, "/", "dwatchtower.johnmgrubbs.io:not-a-port")).status).toBe(403);
    expect((await get(frontendPort, "/", "dwatchtower.johnmgrubbs.io:5174")).status).toBe(200);
  });

  it("proxies API requests to only the configured FastAPI origin", async () => {
    const response = await get(frontendPort, "/api/v1/health/ready?probe=1");
    expect(response.status).toBe(200);
    expect(JSON.parse(response.body)).toEqual({ path: "/api/v1/health/ready?probe=1" });
    expect(response.headers["x-request-id"]).toBe("test-request");
  });

  it("rejects network-path and backslash request targets instead of becoming an open proxy", async () => {
    expect((await get(
      frontendPort,
      `//127.0.0.1:${apiPort}/api/v1/health/ready`,
    )).status).toBe(400);
    expect((await get(
      frontendPort,
      String.raw`/\127.0.0.1:${apiPort}/api/v1/health/ready`,
    )).status).toBe(400);
  });

  it("rejects oversized fixed-length and chunked API request bodies", async () => {
    const requestsBefore = apiRequestCount;
    const fixed = await send(frontendPort, {
      path: "/api/v1/auth/login",
      method: "POST",
      headers: { "Content-Length": "65" },
      chunks: [Buffer.alloc(65, "a")],
    });
    const chunked = await send(frontendPort, {
      path: "/api/v1/auth/login",
      method: "POST",
      chunks: [Buffer.alloc(40, "a"), Buffer.alloc(40, "b")],
    });

    expect(fixed.status).toBe(413);
    expect(chunked.status).toBe(413);
    expect(apiRequestCount).toBe(requestsBefore);
  });

  it("survives an upstream response reset after headers", async () => {
    await requestExpectingAbort(frontendPort, "/api/v1/reset");
    expect((await get(frontendPort, "/")).status).toBe(200);
  });

  it("strips fixed and Connection-nominated hop-by-hop proxy headers", async () => {
    const response = await get(frontendPort, "/api/v1/health/ready", undefined, {
      Connection: "keep-alive, x-remove-request",
      "X-Remove-Request": "secret",
      "Proxy-Authorization": "Basic secret",
      Forwarded: "for=attacker.example",
      "X-Forwarded-For": "attacker.example",
      "X-Forwarded-Prefix": "/admin",
      "X-Forwarded-Client-Cert": "spoofed",
      TE: "trailers",
    });

    expect(lastApiHeaders["x-remove-request"]).toBeUndefined();
    expect(lastApiHeaders["proxy-authorization"]).toBeUndefined();
    expect(lastApiHeaders.forwarded).toBeUndefined();
    expect(lastApiHeaders["x-forwarded-for"]).toBeUndefined();
    expect(lastApiHeaders["x-forwarded-prefix"]).toBeUndefined();
    expect(lastApiHeaders["x-forwarded-client-cert"]).toBeUndefined();
    expect(lastApiHeaders.te).toBeUndefined();
    expect(response.headers["x-remove-response"]).toBeUndefined();
    expect(response.headers["proxy-authenticate"]).toBeUndefined();
  });

  it("uses immutable caching only for fingerprinted Vite assets", async () => {
    const fingerprinted = await get(frontendPort, "/assets/app-ABCDEFGH.js");
    const stableAsset = await get(frontendPort, "/assets/app.js");
    const favicon = await get(frontendPort, "/favicon.svg");
    expect(fingerprinted.headers["cache-control"]).toBe("public, max-age=31536000, immutable");
    expect(stableAsset.headers["cache-control"]).toBe("no-cache");
    expect(favicon.headers["cache-control"]).toBe("no-cache");
  });

  it("returns static assets without falling back for missing files", async () => {
    const asset = await get(frontendPort, "/assets/app.js");
    const missing = await get(frontendPort, "/assets/missing.js");
    expect(asset.status).toBe(200);
    expect(asset.headers["content-type"]).toContain("text/javascript");
    expect(missing.status).toBe(404);
  });

  it("rejects unsupported API origin protocols at startup", () => {
    expect(() => createFrontendServer({ apiOrigin: "file:///etc/passwd", distDir }))
      .toThrow(/HTTP or HTTPS/);
  });

  it.each(["1e6", "64junk", "262144.9", "0", "-1", "9007199254740992"]) (
    "rejects malformed request-body limit %s",
    (maxRequestBodyBytes) => {
      const previous = process.env.WATCHTOWER_MAX_REQUEST_BODY_BYTES;
      process.env.WATCHTOWER_MAX_REQUEST_BODY_BYTES = maxRequestBodyBytes;
      try {
        expect(() => createFrontendServer({ distDir })).toThrow(/positive integer/);
      } finally {
        if (previous === undefined) delete process.env.WATCHTOWER_MAX_REQUEST_BODY_BYTES;
        else process.env.WATCHTOWER_MAX_REQUEST_BODY_BYTES = previous;
      }
    },
  );
});
