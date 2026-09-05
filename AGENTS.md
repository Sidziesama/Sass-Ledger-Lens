# Agent Instructions

- Keep PRISM tracing wired for any future model, agent, retrieval, or tool-call path.
- Never commit `.env`, `PRISMTRACE_API_KEY`, or any other live credential.
- Use `X-PRISMtrace-Key` for PRISM ingest, not a bearer token.
- After changing the trace path, run `npm run trace:preview`; with local credentials, run `npm run trace:handshake`, `npm run trace:send`, and `npm run trace:doctor`.
