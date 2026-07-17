# Backend Authorization Review

## Verdict
**Not verified.** This repository contains the Home Assistant client, not the portal/backend handlers for `/api/ha/bootstrap` or `/api/trials/start`.

## Confirmed Client Behavior
- OAuth uses PKCE and requests the backend API scope.
- Bootstrap and trial requests send `Authorization: Bearer {access_token}`.
- `installationId` and optional `deviceToken` are request data, not client-side credentials.
- Bootstrap responses with a different installation ID are rejected.

## Backend Requirements
- Require a valid Entra access token on both endpoints.
- Validate signature, issuer, audience, expiry, tenant, and allowed algorithm.
- Derive ownership from stable validated claims such as `tid` plus `oid`; do not use email or `installationId` as identity.
- Permit linking only after the authenticated portal confirmation.
- Reject missing or invalid tokens with `401`.
- Reject another account accessing an existing installation with `403` or `404`.
- Never log access tokens or complete claims payloads.

## Required Tests
- Missing, malformed, expired, and wrong-audience tokens are rejected.
- A valid owner can link and bootstrap its installation.
- A different valid account cannot access or relink that installation.
- Changing only `installationId` or `deviceToken` cannot bypass ownership.
- Account switching links the installation only to the newly confirmed account.

## Completion Condition
Review the backend authorization middleware, ownership query, link handler, and tests in the portal/backend repository. Recommendation 6 is complete only when every requirement above is verified.
