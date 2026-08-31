import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { isIP } from "node:net";
import { extname, resolve, sep } from "node:path";
import { pipeline } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";

const FRONTEND_ORIGIN = "http://frontend.local";
const SECURITY_HEADERS = Object.freeze({
  "Content-Security-Policy": "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
});

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const MIME_TYPES = Object.freeze({
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
});

const DEFAULT_ALLOWED_HOSTS = Object.freeze([
  "127.0.0.1",
  "::1",
  "localhost",
  "dwatchtower.johnmgrubbs.io",
]);

function validPort(value) {
  if (value === undefined) return true;
  if (!/^\d{1,5}$/.test(value)) return false;
  const port = Number.parseInt(value, 10);
  return port >= 1 && port <= 65_535;
}

function hostnameFromHeader(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  const authority = value.trim().toLowerCase();
  if (authority.startsWith("[")) {
    const match = /^\[([^\]]+)\](?::(\d{1,5}))?$/.exec(authority);
    if (!match || isIP(match[1]) !== 6 || !validPort(match[2])) return "";
    return match[1];
  }
  const match = /^([a-z0-9.-]+)(?::(\d{1,5}))?$/.exec(authority);
  if (!match || !validPort(match[2])) return "";
  return match[1];
}

function parseOriginForm(value) {
  if (
    typeof value !== "string"
    || !value.startsWith("/")
    || value.startsWith("//")
    || value.includes("\\")
    || /%5c/i.test(value)
    || /[\u0000-\u001f\u007f]/.test(value)
  ) return null;
  let parsed;
  try {
    parsed = new URL(value, FRONTEND_ORIGIN);
  } catch {
    return null;
  }
  if (parsed.origin !== FRONTEND_ORIGIN || parsed.hash) return null;
  return parsed;
}

function validatedApiOrigin(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("WATCHTOWER_API_ORIGIN must be a valid HTTP or HTTPS origin");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol)
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) throw new Error("WATCHTOWER_API_ORIGIN must be an HTTP or HTTPS origin without credentials or a path");
  return parsed;
}

function connectionHeaderNames(headers) {
  const value = headers.connection;
  const values = Array.isArray(value) ? value : [value];
  return new Set(values
    .filter((item) => typeof item === "string")
    .flatMap((item) => item.split(","))
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean));
}

function stripHopByHopHeaders(headers) {
  const nominated = connectionHeaderNames(headers);
  return Object.fromEntries(Object.entries(headers).filter(([name, value]) => {
    const lowerName = name.toLowerCase();
    return value !== undefined
      && !HOP_BY_HOP_HEADERS.has(lowerName)
      && lowerName !== "forwarded"
      && !lowerName.startsWith("x-forwarded-")
      && !nominated.has(lowerName);
  }));
}

function writeResponse(res, status, body, headers = {}) {
  res.writeHead(status, { ...SECURITY_HEADERS, ...headers });
  res.end(body);
}

function forwardBufferedRequest(req, res, apiOrigin, requestUrl, body) {
  const target = new URL(apiOrigin.origin);
  target.pathname = requestUrl.pathname;
  target.search = requestUrl.search;
  const headers = {
    ...stripHopByHopHeaders(req.headers),
    host: target.host,
    "content-length": String(body.length),
  };

  const transport = target.protocol === "https:" ? httpsRequest : httpRequest;
  let upstreamResponse;
  const upstream = transport(target, {
    method: req.method,
    headers,
  }, (response) => {
    upstreamResponse = response;
    const responseHeaders = {
      ...stripHopByHopHeaders(response.headers),
      ...SECURITY_HEADERS,
    };
    res.writeHead(response.statusCode || 502, responseHeaders);
    pipeline(response, res, (error) => {
      if (error && !res.destroyed) res.destroy();
    });
  });

  res.once("close", () => {
    if (!res.writableEnded) {
      upstream.destroy();
      upstreamResponse?.destroy();
    }
  });
  upstream.setTimeout(30_000, () => upstream.destroy(new Error("API proxy timeout")));
  upstream.on("error", () => {
    if (!res.headersSent) writeResponse(res, 502, "Bad Gateway");
    else res.destroy();
  });
  upstream.end(body);
}

function positiveSafeInteger(value, name) {
  const raw = typeof value === "number" ? String(value) : value;
  if (typeof raw !== "string" || !/^[1-9]\d*$/.test(raw)) {
    throw new Error(`${name} must be a positive integer`);
  }
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function rejectRequestBody(req, res, status, message) {
  res.shouldKeepAlive = false;
  writeResponse(res, status, message, { Connection: "close" });
  req.resume();
}

function proxyRequest(req, res, apiOrigin, requestUrl, maxRequestBodyBytes) {
  const contentLength = req.headers["content-length"];
  if (contentLength !== undefined) {
    if (typeof contentLength !== "string" || !/^\d+$/.test(contentLength)) {
      rejectRequestBody(req, res, 400, "Bad Request");
      return;
    }
    const declaredBytes = Number(contentLength);
    if (!Number.isSafeInteger(declaredBytes)) {
      rejectRequestBody(req, res, 400, "Bad Request");
      return;
    }
    if (declaredBytes > maxRequestBodyBytes) {
      rejectRequestBody(req, res, 413, "Payload Too Large");
      return;
    }
  }

  const chunks = [];
  let receivedBytes = 0;
  let rejected = false;
  req.on("data", (chunk) => {
    if (rejected) return;
    receivedBytes += chunk.length;
    if (receivedBytes > maxRequestBodyBytes) {
      rejected = true;
      rejectRequestBody(req, res, 413, "Payload Too Large");
      return;
    }
    chunks.push(chunk);
  });
  req.on("end", () => {
    if (!rejected) {
      forwardBufferedRequest(req, res, apiOrigin, requestUrl, Buffer.concat(chunks));
    }
  });
  req.on("aborted", () => {
    rejected = true;
    chunks.length = 0;
  });
  req.on("error", () => {
    rejected = true;
    chunks.length = 0;
    if (!res.headersSent) writeResponse(res, 400, "Bad Request");
  });
}

async function serveStatic(req, res, distDir, requestUrl) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    writeResponse(res, 405, "Method Not Allowed", { Allow: "GET, HEAD" });
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(requestUrl.pathname);
  } catch {
    writeResponse(res, 400, "Bad Request");
    return;
  }

  const root = resolve(distDir);
  const requested = pathname === "/" ? "/index.html" : pathname;
  let candidate = resolve(root, `.${requested}`);
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    writeResponse(res, 403, "Forbidden");
    return;
  }

  let metadata;
  try {
    metadata = await stat(candidate);
  } catch {
    metadata = null;
  }

  if (!metadata?.isFile()) {
    if (extname(pathname)) {
      writeResponse(res, 404, "Not Found");
      return;
    }
    candidate = resolve(root, "index.html");
    try {
      metadata = await stat(candidate);
    } catch {
      writeResponse(res, 500, "Frontend bundle unavailable");
      return;
    }
  }

  const extension = extname(candidate).toLowerCase();
  const headers = {
    "Content-Type": MIME_TYPES[extension] || "application/octet-stream",
    "Content-Length": metadata.size,
    "Cache-Control": /^\/assets\/[^/]+-[A-Za-z0-9_-]{8,}\.[^/]+$/.test(requestUrl.pathname)
      ? "public, max-age=31536000, immutable"
      : "no-cache",
  };
  res.writeHead(200, { ...SECURITY_HEADERS, ...headers });
  if (req.method === "HEAD") {
    res.end();
    return;
  }
  const stream = createReadStream(candidate);
  stream.on("error", () => res.destroy());
  stream.pipe(res);
}

export function createFrontendServer({
  apiOrigin = process.env.WATCHTOWER_API_ORIGIN || "http://api:8000",
  allowedHosts = DEFAULT_ALLOWED_HOSTS,
  distDir = fileURLToPath(new URL("./dist/", import.meta.url)),
  maxRequestBodyBytes = process.env.WATCHTOWER_MAX_REQUEST_BODY_BYTES || "262144",
} = {}) {
  const upstreamOrigin = validatedApiOrigin(apiOrigin);
  const requestBodyLimit = positiveSafeInteger(
    maxRequestBodyBytes,
    "WATCHTOWER_MAX_REQUEST_BODY_BYTES",
  );
  const allowed = new Set(allowedHosts.map((host) => host.toLowerCase()));
  return createServer((req, res) => {
    if (!allowed.has(hostnameFromHeader(req.headers.host))) {
      writeResponse(res, 403, "Forbidden Host");
      return;
    }
    const requestUrl = parseOriginForm(req.url);
    if (!requestUrl) {
      writeResponse(res, 400, "Bad Request");
      return;
    }
    if (requestUrl.pathname === "/api" || requestUrl.pathname.startsWith("/api/")) {
      proxyRequest(req, res, upstreamOrigin, requestUrl, requestBodyLimit);
      return;
    }
    void serveStatic(req, res, distDir, requestUrl).catch(() => {
      if (!res.headersSent) writeResponse(res, 500, "Internal Server Error");
      else res.destroy();
    });
  });
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  const port = positiveSafeInteger(process.env.PORT || "5173", "PORT");
  if (port > 65_535) throw new Error("PORT must be between 1 and 65535");
  const server = createFrontendServer();
  server.listen(port, "0.0.0.0", () => {
    console.log(`Watchtower frontend listening on http://0.0.0.0:${port}`);
  });
}
