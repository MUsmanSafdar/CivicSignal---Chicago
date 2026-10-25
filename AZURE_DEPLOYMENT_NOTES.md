# CivicSignal on Azure: deployment notes (v1.0)

Microsoft-only services (Entra ID, App Service, Table Storage, Key Vault, Application Insights). The app makes no calls to any other AI vendor. The only outbound call is the public Grants.gov API.

## 1. Architecture
- **Azure App Service (Linux, Python 3.11)** runs `startup.sh`.
- **App Service Authentication (Easy Auth) with Microsoft Entra ID** signs users in and adds `X-Ms-Client-Principal*` headers. The app trusts them only when `WEBSITE_AUTH_ENABLED=True` (set by App Service) or `TRUST_AUTH_HEADERS=1`. Never expose the app directly to the internet without Easy Auth in front of it, or anyone could forge those headers.
- **Azure Table Storage** (`AUDIT_CONNECTION_STRING`) holds the audit chain, workspace state, settings and the Grants.gov cache. Without that variable the app falls back to a local SQLite file, which is fine for development and not for production (App Service local disk is not durable across scale-out).
- **Key Vault** holds the storage connection string; App Service reads it through a Key Vault reference.

## 2. Access control (RBAC)
Roles come from Entra **App Roles** (`viewer`, `reviewer`, `official`, `admin`) in the token, or from the env lists below.

| Permission | Roles |
|---|---|
| View dashboards and CivicSignal | everyone, including anonymous |
| Publish eligibility rules | reviewer, admin |
| Edit project facts | reviewer, official, admin |
| Approve or hold a project | official, admin |
| Refresh Grants.gov notices | reviewer, official, admin |
| Upload data, change county scope, confirm verified data, run the tamper demo | admin |

Audit actor = `user:<verified email>`. It is never typed text.

## 3. Environment variables
| Variable | Purpose | Default |
|---|---|---|
| `AUDIT_CONNECTION_STRING` | Azure Table Storage connection string (use a Key Vault reference) | unset, so SQLite |
| `AUDIT_DB_PATH` | SQLite file path (dev) | `civicsignal_data.sqlite3` |
| `TENANT_ID` | Separates stored data per customer | `default` |
| `ALLOWED_COUNTIES` | Comma-separated county list, or `ALL` | Chicago-area 7 counties |
| `ROLE_ADMINS`, `ROLE_OFFICIALS`, `ROLE_REVIEWERS` | Comma-separated emails granted that role (in addition to token roles) | empty |
| `TRUST_AUTH_HEADERS` | `1` to trust Easy Auth headers when `WEBSITE_AUTH_ENABLED` is not set | unset |
| `ALLOWED_EMAILS`, `DEV_USER_EMAIL` | Local-development sign-in only. `DEV_USER_EMAIL` must be listed in `ALLOWED_EMAILS`. **Never set in production.** | unset |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Turns on Azure Application Insights (also `pip install azure-monitor-opentelemetry`) | unset, so logs go to stdout only |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` so App Service installs requirements | |

`ADMIN_PASSWORD` is gone. Admin access now requires a signed-in identity with the admin role.

## 4. Deploy
1. Create a Linux App Service (Python 3.11) and a Storage account (Table service).
2. Turn on **Authentication** (Entra ID, "Require authentication" off so the public pages stay open, or on if the whole tenant is internal). Define the four App Roles in the app registration and assign people.
3. Put the storage connection string in Key Vault; give the App Service a managed identity with *Key Vault Secrets User*; set `AUDIT_CONNECTION_STRING` to `@Microsoft.KeyVault(SecretUri=...)`.
4. Set `TENANT_ID`, `ALLOWED_COUNTIES`, `SCM_DO_BUILD_DURING_DEPLOYMENT=true`.
5. Startup command: `bash startup.sh`.
6. Deploy (zip deploy, GitHub Actions, or `az webapp up`).
7. Sign in as an admin, open **Audit trail → Verify saved record** to confirm storage works.

## 5. Retention and tamper-resistance (recommendations)
The hash chain makes edits **detectable**. It does not make them **impossible**: whoever holds the storage key can rewrite rows and recompute hashes. For production:
- Turn on **blob versioning and soft delete** for any exported packets, and export the chain head hash on a schedule to **immutable (WORM) Blob Storage** with a time-based retention policy, so a later rewrite can be proven.
- Restrict the storage key; use Entra RBAC (*Storage Table Data Contributor* for the app only) and disable shared-key access where practical.
- Consider **Azure SQL ledger tables** or **Confidential Ledger** if you need database-enforced tamper evidence.
- Set a retention period that matches your records schedule (public-records laws often require years); document it in PRIVACY.md.
- Back up the table account (geo-redundant storage).

## 6. Operations
- Logs: one JSON line per login, rule publication and decision on the `civicsignal` logger (App Service log stream). Lines hold the actor email and ids only, never reason text. Set `APPLICATIONINSIGHTS_CONNECTION_STRING` and install `azure-monitor-opentelemetry` to send them to Application Insights.
- Funding Watch calls `api.grants.gov` from the App Service; allow outbound HTTPS to it.
- Dependency scanning: `pip-audit -r requirements.txt`. CI runs it (report only) on every push.
- Rate limiting: each browser session is limited to 12 chat messages per minute and 500 characters per message (`rate_limit.py`). That does not stop a determined client opening many sessions, so also put Azure Front Door (WAF rate-limit rule) in front of the App Service.
- Secrets: none in code. `.env` is git-ignored; use Key Vault references in App Service.
- Security checklist: Easy Auth on; `ALLOWED_EMAILS`/`DEV_USER_EMAIL` unset; storage shared-key access restricted; HTTPS only; minimum TLS 1.2.

## 7. Microsoft-only AI rule
No Claude, direct OpenAI, DeepSeek or other non-Microsoft AI calls. If AI is added later it must use Azure OpenAI or Azure AI services, secrets in Key Vault, and a person must still make every approval, hold and publication.
