import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as dashboard from "../pip-dashboard.js";
import {
  PIP_DEFAULT_API_URL,
  describePipHurdle,
  normalizePipApiUrl,
  parseOptionalNumber,
  parsePipCandidates,
  pipApiErrorMessage,
} from "../pip-shared.js";

const INVALID_CANDIDATE = (entry) => `Invalid replacement candidate: ${entry}. Use SYMBOL:score from 0 to 100.`;

test("the workbench keeps exporting the shared default URL and hurdle describer", () => {
  assert.equal(PIP_DEFAULT_API_URL, "https://stockscanner-pip-api.onrender.com");
  assert.equal(dashboard.PIP_DEFAULT_API_URL, PIP_DEFAULT_API_URL);
  assert.equal(dashboard.describePipHurdle, describePipHurdle);
  assert.deepEqual(describePipHurdle(null), ["Return hurdle: unavailable from this API version."]);
});

test("the shared helpers stay free of browser globals", async () => {
  const source = await readFile(new URL("../pip-shared.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\b(document|window|localStorage|sessionStorage|fetch|XMLHttpRequest|innerHTML)\b/);
});

test("API URLs must be present, parseable and secure", () => {
  for (const blank of ["", "   ", null, undefined, 7]) {
    assert.deepEqual(normalizePipApiUrl(blank), { ok: false, error: "Enter the PIP API URL." });
  }
  for (const garbage of ["not a url", "stockscanner-pip-api.onrender.com", "https://"]) {
    assert.deepEqual(normalizePipApiUrl(garbage), {
      ok: false,
      error: "Enter a full PIP API URL that starts with https://.",
    });
  }
  for (const insecure of [
    "http://api.example.test",
    "http://localhost.evil.test",
    "http://127.0.0.1.evil.test",
    "ftp://localhost",
    "ws://localhost:8000",
  ]) {
    assert.deepEqual(normalizePipApiUrl(insecure), { ok: false, error: "Use HTTPS for the PIP API URL." }, insecure);
  }
});

test("API URLs may not carry credentials, a query string or a fragment", () => {
  const error = "The PIP API URL must not contain credentials, a query string or a fragment.";
  for (const url of [
    "https://user:pass@api.example.test",
    "https://user@api.example.test",
    "https://stockscanner-pip-api.onrender.com@evil.example.test",
    "https://api.example.test/?token=1",
    "https://api.example.test?x",
    "https://api.example.test/#section",
  ]) {
    assert.deepEqual(normalizePipApiUrl(url), { ok: false, error }, url);
  }
});

test("API URLs are normalized to an origin plus path without trailing slashes", () => {
  assert.deepEqual(normalizePipApiUrl(" https://api.example.test/ "), {
    ok: true,
    url: "https://api.example.test",
    origin: "https://api.example.test",
    isLocal: false,
    isDefault: false,
  });
  assert.deepEqual(normalizePipApiUrl("https://api.example.test:8443/pip//"), {
    ok: true,
    url: "https://api.example.test:8443/pip",
    origin: "https://api.example.test:8443",
    isLocal: false,
    isDefault: false,
  });
  assert.deepEqual(normalizePipApiUrl("HTTPS://API.Example.test"), {
    ok: true,
    url: "https://api.example.test",
    origin: "https://api.example.test",
    isLocal: false,
    isDefault: false,
  });
});

test("plain HTTP is accepted only for localhost and 127.0.0.1", () => {
  assert.deepEqual(normalizePipApiUrl("http://localhost:8000/"), {
    ok: true,
    url: "http://localhost:8000",
    origin: "http://localhost:8000",
    isLocal: true,
    isDefault: false,
  });
  const loopback = normalizePipApiUrl("http://127.0.0.1:8000");
  assert.equal(loopback.ok, true);
  assert.equal(loopback.isLocal, true);
  assert.equal(normalizePipApiUrl("https://localhost").isLocal, true);
});

test("only the exact default origin counts as the default service", () => {
  const exact = normalizePipApiUrl(`${PIP_DEFAULT_API_URL}/`);
  assert.equal(exact.ok, true);
  assert.equal(exact.url, PIP_DEFAULT_API_URL);
  assert.equal(exact.isDefault, true);
  assert.equal(exact.isLocal, false);
  assert.equal(normalizePipApiUrl("https://STOCKSCANNER-pip-api.onrender.com:443").isDefault, true);
  for (const lookalike of [
    "https://stockscanner-pip-api.onrender.com.evil.example.test",
    "https://evil-stockscanner-pip-api.onrender.com",
    "https://onrender.com",
    "https://stockscanner-pip-api.onrender.com:8443",
    "http://localhost:10000",
  ]) {
    const result = normalizePipApiUrl(lookalike);
    assert.equal(result.ok, true, lookalike);
    assert.equal(result.isDefault, false, lookalike);
  }
});

test("a plain API error message is shown as it was sent", () => {
  assert.equal(
    pipApiErrorMessage({ detail: "Import this holding into the selected portfolio before analyzing it." }, 422),
    "Import this holding into the selected portfolio before analyzing it.",
  );
});

test("a missing or unusable error body falls back to the HTTP status", () => {
  for (const payload of [null, undefined, {}, { detail: null }, { detail: "" }, { detail: "   " }, { detail: 7 }, { detail: {} }, "oops"]) {
    assert.equal(pipApiErrorMessage(payload, 500), "PIP API request failed (500).", JSON.stringify(payload));
  }
  assert.equal(pipApiErrorMessage(null, 0), "PIP API request failed.");
  assert.equal(pipApiErrorMessage(null), "PIP API request failed.");
});

test("validation errors name the field and the rule without echoing the input", () => {
  const message = pipApiErrorMessage({
    detail: [{
      type: "greater_than",
      loc: ["body", "position", "market_price"],
      msg: "Input should be greater than 0",
      input: "SECRET-INPUT",
      ctx: { gt: "SECRET-CONTEXT" },
    }],
  }, 422);
  assert.equal(message, "The API rejected these values: position.market_price: Input should be greater than 0.");
  assert.doesNotMatch(message, /SECRET/);
});

test("validation locations drop one request root and render list positions", () => {
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["body", "peer_scores", 3, "score"], msg: "Field required" }] }, 422),
    "The API rejected these values: peer_scores[3].score: Field required.",
  );
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["query", "limit"], msg: "Input should be at most 500" }] }, 422),
    "The API rejected these values: limit: Input should be at most 500.",
  );
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["body", "body", "x"], msg: "Bad" }] }, 422),
    "The API rejected these values: body.x: Bad.",
  );
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["body"], msg: "Input should be a valid dictionary" }] }, 422),
    "The API rejected these values: Input should be a valid dictionary.",
  );
  assert.equal(
    pipApiErrorMessage({ detail: [{ msg: "Field required" }] }, 422),
    "The API rejected these values: Field required.",
  );
});

test("custom validation messages lose Pydantic's generated prefix", () => {
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["body", "symbol"], msg: "Value error, Symbol is not valid." }] }, 422),
    "The API rejected these values: symbol: Symbol is not valid.",
  );
  assert.equal(
    pipApiErrorMessage({ detail: [{ loc: ["body", "symbol"], msg: "Assertion error, nope" }] }, 422),
    "The API rejected these values: symbol: nope.",
  );
});

test("a long list of validation errors is capped, and so is each message", () => {
  const detail = ["a", "b", "c", "d", "e"].map((name) => ({ loc: ["body", name], msg: `${name} is bad` }));
  assert.equal(
    pipApiErrorMessage({ detail }, 422),
    "The API rejected these values: a: a is bad; b: b is bad; c: c is bad; and 2 more.",
  );
  const long = pipApiErrorMessage({ detail: [{ loc: ["body", "x"], msg: "y".repeat(500) }] }, 422);
  assert.equal(long, `The API rejected these values: x: ${"y".repeat(200)}.`);
});

test("malformed validation items are skipped", () => {
  const junk = [null, 5, "text", {}, { msg: "" }, { msg: "   " }, { msg: 7 }, { msg: "Value error, " }];
  assert.equal(pipApiErrorMessage({ detail: junk }, 422), "PIP API request failed (422).");
  assert.equal(pipApiErrorMessage({ detail: [] }, 422), "PIP API request failed (422).");
  assert.equal(
    pipApiErrorMessage({ detail: [...junk, { loc: [{}, null, "field", -0.5], msg: "Kept" }] }, 422),
    "The API rejected these values: field: Kept.",
  );
});

test("optional numbers: blank is none and values are checked against their bounds", () => {
  for (const blank of ["", "   ", null, undefined]) {
    assert.equal(parseOptionalNumber("Price", blank), null);
  }
  assert.equal(parseOptionalNumber("Price", " 12.5 "), 12.5);
  assert.equal(parseOptionalNumber("Price", "0"), 0);
  assert.equal(parseOptionalNumber("Price", "-3"), -3);
  assert.equal(parseOptionalNumber("Price", 5), 5);
  assert.equal(parseOptionalNumber("Price", "0", { min: 0, max: 100 }), 0);
  assert.equal(parseOptionalNumber("Price", "100", { min: 0, max: 100 }), 100);
  for (const bad of ["abc", "12abc", "NaN", "Infinity", "-Infinity", "1e999"]) {
    assert.throws(() => parseOptionalNumber("Price", bad), { message: "Price must be a number." }, bad);
  }
  assert.throws(() => parseOptionalNumber("Price", "-1", { min: 0 }), { message: "Price must be at least 0." });
  assert.throws(() => parseOptionalNumber("Price", "101", { max: 100 }), { message: "Price must be no more than 100." });
  assert.throws(() => parseOptionalNumber("Price", "0.001", { min: 0.01 }), { message: "Price must be at least 0.01." });
});

test("replacement candidates: blank is none and symbols are upper-cased", () => {
  assert.deepEqual(parsePipCandidates(""), []);
  assert.deepEqual(parsePipCandidates("   "), []);
  assert.deepEqual(parsePipCandidates(null), []);
  assert.deepEqual(parsePipCandidates(" aaa : 50 , bbb:60.5,CCC.B:0,DDD-1:100"), [
    { symbol: "AAA", score: 50 },
    { symbol: "BBB", score: 60.5 },
    { symbol: "CCC.B", score: 0 },
    { symbol: "DDD-1", score: 100 },
  ]);
});

test("replacement candidates may be separated by commas or new lines, and empty entries are skipped", () => {
  assert.deepEqual(parsePipCandidates("AAA:50,\nBBB:60,\n"), [
    { symbol: "AAA", score: 50 },
    { symbol: "BBB", score: 60 },
  ]);
  assert.deepEqual(parsePipCandidates(",, AAA:1 ,,"), [{ symbol: "AAA", score: 1 }]);
  assert.deepEqual(parsePipCandidates("AAA:50\r\nBBB:60"), [
    { symbol: "AAA", score: 50 },
    { symbol: "BBB", score: 60 },
  ]);
});

test("a malformed replacement candidate is rejected with the entry shown as typed", () => {
  for (const entry of ["AAA", "AAA:", "AAA:101", "AAA:-1", "AAA:50:1", "<b>:50", "AAA:abc", ":50", ".A:50", "-A:50", `${"A".repeat(31)}:5`]) {
    assert.throws(() => parsePipCandidates(entry), { message: INVALID_CANDIDATE(entry) }, entry);
  }
  assert.throws(() => parsePipCandidates("AAA:50,  BBB:  "), { message: INVALID_CANDIDATE("BBB:") });
  assert.deepEqual(parsePipCandidates(`${"A".repeat(30)}:5`), [{ symbol: "A".repeat(30), score: 5 }]);
});

test("replacement candidates can be limited in number and required to be unique", () => {
  assert.equal(parsePipCandidates("AAA:1,BBB:2", { max: 2 }).length, 2);
  assert.throws(() => parsePipCandidates("AAA:1,BBB:2,CCC:3", { max: 2 }), {
    message: "Enter at most 2 replacement candidates.",
  });
  assert.equal(parsePipCandidates("AAA:1,aaa:2").length, 2);
  assert.throws(() => parsePipCandidates("AAA:1,aaa:2", { unique: true }), {
    message: "Each replacement candidate symbol may appear only once.",
  });
  assert.equal(parsePipCandidates("AAA:1,BBB:2", { unique: true, max: 500 }).length, 2);
});
