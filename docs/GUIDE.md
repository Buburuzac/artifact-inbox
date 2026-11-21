# artifact-inbox: user guide

`artifact-inbox` is an artifact inbox. AI agents push documents (PDF, markdown, HTML, text) into it; you read them in the
browser, sort them, and mark them done.

## Using the web UI (your `INBOX_BASE_URL`)

- **Tabs**: Unread / Done / All, with counts.
- **Sorting**: "Newest first" (default) or "By category" (grouped, with counts). Choose a category in the sidebar
  to filter; choose an inbox view to clear the filter.
- **Open an item**: PDFs render in the browser's viewer (Download is the fallback), markdown is rendered and
  sanitised, HTML is shown in a sandboxed frame (scripts run, no network; localStorage persists per item), text is shown as-is.
- **Actions**: Mark done / Mark unread, Delete (asks for confirmation). "Mark all done" in the list applies to the
  current category filter (and to everything unread if no filter is set).
- **Projects**: create one from **All projects** in the sidebar. Open a project to see only its artifacts. On an
  artifact card or page, choose **Project** and select **Move** or **Save project** to file it, transfer it to another
  project, or set it to **Unassigned**. Agents can call `list_projects` and pass the returned ID as
  `project_id` to `push_artifact`; REST accepts the same multipart field. Deleting a project keeps its artifacts
  and removes their project assignment.
- **Share links**: open an artifact, choose a link lifetime (24 hours, 7 days, 30 days or no expiry), and select
  **Create share link**. Copy the URL when it appears; it is shown once. Anyone with that URL can read and download
  that artifact without signing in. Revoke the link on the artifact page to cut off access immediately. Other
  artifacts and controls remain private.
- Dark mode and phone layout follow the device.

## Connecting an agent

**Recommended: one token per agent.** Open *Agents* in the sidebar, enter a name (e.g. `claude-code`) and click
*Create install link*. Paste the shown line (`install this: https://.../install?claim=...`) to the agent. The link is
shown once, works once, and expires (60 minutes by default, `INBOX_CLAIM_TTL_MIN`). The agent trades it for its own
token; items it pushes are labelled with the name you chose, whatever it claims. To cut an agent off, click *Revoke*
on the Agents page; other agents are unaffected. Unused links are listed there and can be cancelled.

**Alternative: the shared admin token.**

Give the agent this and nothing else: **"install this: https://inbox.example.com/install"**, plus the token (ask it to
keep the token private). The page walks the agent through MCP setup, skill install and verification. The token is
`INBOX_API_TOKEN` in your `.env`. (`https://inbox.example.com` in the docs is replaced with your `INBOX_BASE_URL` when served.)

Public (no login) paths include `/install`, `/install/SKILL.md`, and `/s/<secret>` (a read-only share URL).
`/mcp` and `/api/*` need the bearer token; the normal UI remains protected by `INBOX_UI_PASSWORD` (basic auth)
or by your reverse proxy (see DEPLOYMENT.md).

## Interfaces for agents

- **MCP** `https://inbox.example.com/mcp` (streamable HTTP, bearer): `push_artifact`, `move_artifact`, `list_items`, `get_item`,
  `mark_done`, `list_categories`, `list_projects`, `create_project`, `delete_project`, `delete_item`.
- **REST** `POST /api/push` (multipart: `file`, `title`, `category`, `project_id`, `summary`, `source_agent`, `type`), same bearer:
  ```sh
  curl -sS -X POST https://inbox.example.com/api/push -H "Authorization: Bearer $INBOX_API_TOKEN" \
    -F file=@report.pdf -F title="Report title" -F category=research -F source_agent=me -F summary="One line."
  ```
  Responses: `201 {id, link, type, size, category, project_id}`, `400` bad input, `401` token, `413` over 50 MB, `415` unsupported type.
  `GET /api/projects` lists projects and their IDs; `POST /api/projects` with JSON `{"name":"Project name"}`
  creates one. `PATCH /api/items/<id>/project` with JSON `{"project_id":"<project id>"}` moves an existing
  artifact without uploading it again; use `null` to leave it unassigned. These routes require the same bearer token.

## Rules the server enforces

- 50 MB limit. PDFs are detected by `%PDF-` bytes, never by extension; a file named or declared PDF without them is
  rejected. Binary non-PDF content is rejected.
- Categories are lowercased/trimmed (max 40 chars); default `general`.
- Files are stored under random ids; uploaded names never reach the disk. Served with correct Content-Type and
  `nosniff`; HTML/markdown are untrusted (sandboxed/sanitised).
- `push_artifact(url=...)` only fetches public addresses.

## Operating

```sh
docker compose up -d            # start / apply changes to .env or compose.yml
docker compose up -d --build    # rebuild after code, docs or skill changes
docker compose logs -f artifact-inbox
```
- Data: `inbox.db` and `files/` in the data volume (`./data` by default). Back this directory up.
- **Rotate the token**: `openssl rand -hex 32`, set `INBOX_API_TOKEN` in `.env` (mode 600), `docker compose up -d`,
  then update every agent's config.
- Edit the skill in `skill/SKILL.md` and rebuild; agents re-download it from `/install/SKILL.md`.
- Edit this page's source in `docs/INSTALL.md`; rebuild to publish.
- Tests: `python3 -m venv /tmp/v && /tmp/v/bin/pip install -r requirements.txt pytest && /tmp/v/bin/python -m pytest -q tests`

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser shows a login loop | Your auth proxy, not `artifact-inbox`; test `/healthz` inside the container. |
| Agent gets `401` | Wrong token, or missing `Bearer ` prefix. |
| Agent gets a redirect/HTML from `/mcp` | The proxy is sending `/mcp` and `/api` through your SSO; exempt them (see DEPLOYMENT.md). |
| PDF pane empty | Browser has no PDF plugin; use Download. |
| Container unhealthy | `docker compose logs artifact-inbox`; check the data directory is writable by uid 1000. |
