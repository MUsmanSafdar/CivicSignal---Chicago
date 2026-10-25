# Privacy notice

> DRAFT for review by your organization's counsel and privacy officer. Fill in the bracketed items for your deployment.

**Last updated:** 2026-10-25

## What the Service collects
- **Sign-in identity** (work email, display name, identity provider, and role) from Microsoft Entra ID through Azure App Service Authentication. Passwords are never seen or stored by the app.
- **Audit records**: who published a rule, approved or held a project, corrected a fact, or confirmed verified data; when; and the reason text they typed. These records are append-only and hash-chained.
- **Workspace state**: project facts, published rules and decisions for the tenant.
- **Uploaded files** (county risk, capacity, complaints, PDFs) that administrators choose to load.
- **Chat messages** typed into the Hazard Assistant. They are answered by a rule-based engine inside the app, with no outside AI service, and are kept only in the browser session.
- **Funding-notice cache**: public Grants.gov notices.

## What it does not collect
No advertising or tracking cookies are set by the app. Do not type your name, address or medical details into the chat or reason boxes; the app does not need them.

## Why
To run the tool, show who made each decision, and let the Operator reconstruct how a recommendation was reached.

## Where it is stored
In the Operator's Azure subscription (Azure Table Storage or the local SQLite file in development). Access is limited by Azure role-based access control. Retention: `[Operator to set; see AZURE_DEPLOYMENT_NOTES.md for WORM and retention recommendations]`.

## Sharing
Data is not sold or shared for advertising. It may be disclosed where public-records or other laws require it. Because decisions by public officials can be public records, assume reason text may be released.

## Your choices
Ask the Operator to correct or export your account details: `[privacy contact]`. Audit records are intentionally not editable.

## Language access
Public pages are available in English and Spanish (see ACCESSIBILITY.md for translation review status).
