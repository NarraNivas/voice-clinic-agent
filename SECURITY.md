# Security

This is a portfolio demo for a fictional clinic. It holds no real patient data and it is not
deployed to the internet. The notes below say what is protected, what is not, and how to report a
problem.

## Reporting a problem

Please don't report security problems in a public issue with the details. Open a GitHub issue that
says only "I have a security report" and asks for a private channel. The details can then go through
that channel. Once the private vulnerability reporting option is switched on for this repository, use
that instead.

## What is protected

- **Tool routes (`/tools/*`)** need a shared secret in the `X-Tool-Secret` header. With no secret
  configured they return 503, so they fail closed. The secret is compared in constant time.
- **Demo API writes** (`/api/*`, any method except GET, HEAD, and OPTIONS) are refused when a
  browser sends an `Origin` header naming another host. This blocks cross-site writes from a
  browser. Requests with no `Origin` header are not affected.
- **Tunnel scope:** only the tools-only app (`create_tools_app`) is meant to be reachable from the
  internet. It does not serve the staff queue, analytics, outbox, or the demo pages.
- **Error responses** use one fixed shape and never include stack traces or the caller's text.
- **Secrets stay out of git.** `.env`, the SQLite databases, backups, and logs are gitignored. The
  repository history was checked for credentials before it was made public.
- **Third-party script:** the ElevenLabs widget is pinned to a released version and checked with a
  Subresource Integrity hash. The browser refuses any other file at that URL.

## What is not protected

- **The demo API has no login.** Anyone who can reach it can read the staff queue and analytics,
  and change a staff request's status. It is designed for `127.0.0.1` only. Do not put it behind a
  tunnel or a public host.
- **No rate limiting** on any route. Add it before any real traffic.
- **No authentication for staff.** The staff queue is a local view.
- **The records system is a simulator.** Nothing is sent to a real CRM.

## Dependencies

`backend/requirements.lock` pins every installed package. The pinned set was checked with
`pip-audit` and had no known vulnerabilities at the time of the check.
