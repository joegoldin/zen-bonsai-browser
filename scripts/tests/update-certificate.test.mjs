// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { X509Certificate } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const certificate = new X509Certificate(
  readFileSync(new URL("../../build/signing/public_key.der", import.meta.url)),
);

// The inherited trust root must never be accepted by a Bonsai updater.
const upstreamFingerprint =
  "03:6B:2D:0F:B6:D0:81:02:34:63:FF:4B:26:BB:B4:8A:8E:C3:30:41:4A:B1:EB:36:99:9D:95:3D:85:23:AA:8B";

test("Bonsai updates do not trust the inherited upstream signing key", () => {
  assert.notEqual(certificate.fingerprint256, upstreamFingerprint);
});

test("the update certificate identifies the fork", () => {
  assert.match(certificate.subject, /^CN=Zen Bonsai MAR Signing$/m);
});

test("the public update certificate is a self-signed RSA-4096 signing leaf", () => {
  assert.equal(certificate.publicKey.asymmetricKeyType, "rsa");
  assert.equal(certificate.publicKey.asymmetricKeyDetails.modulusLength, 4096);
  assert.equal(certificate.ca, false);
  assert.ok(certificate.keyUsage.includes("1.3.6.1.5.5.7.3.3"));
  assert.equal(certificate.issuer, certificate.subject);
  assert.ok(certificate.verify(certificate.publicKey));
});

test("the public update certificate is currently valid", () => {
  const now = Date.now();
  assert.ok(Date.parse(certificate.validFrom) <= now);
  assert.ok(Date.parse(certificate.validTo) > now);
});

for (const slot of [
  "release_primary",
  "release_secondary",
  "dep1",
  "dep2",
  "xpcshellCertificate",
]) {
  test(`updater certificate slot ${slot} trusts only Bonsai`, () => {
    const path = new URL(
      `../../src/toolkit/mozapps/update/updater/${slot}.der`,
      import.meta.url,
    );
    assert.ok(
      existsSync(path),
      `${slot} must override the inherited certificate`,
    );
    assert.deepEqual(readFileSync(path), certificate.raw);
  });
}
