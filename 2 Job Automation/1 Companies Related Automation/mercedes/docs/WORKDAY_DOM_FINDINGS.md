# Workday (MBTI tenant) DOM findings — verified 2026-09-15

Everything below was verified live against
`https://mercedesbenztechinnovation.wd3.myworkdayjobs.com/en-US/MBTI_JOBPORTAL`
during the R0006909 automation research (17 probe iterations). If Workday's
frontend changes, re-verify here first — this document is the map.

## 1. Navigation / URLs

- Deep links **404**: both `/details/<slug>-<R0006xxx>` and
  `/details/<slug>-<R0006xxx>/apply` render "The page you are looking for
  doesn't exist". The user-supplied URL (with `/apply`) also 404s.
- The reliable entry is the portal home → search list → job link:
  1. `goto(PORTAL_BASE)` — establishes session (deep links stay broken even
     after session is established, so client-side navigation is mandatory).
  2. Dismiss the cookie banner ("Accept Cookies" / "Decline" buttons).
  3. Find `a[data-automation-id="jobTitle"][href*="<R0006xxx>"]` in the list
     (all 11 portal jobs are in that list, no search needed for these).
  4. Click it → real URL is `/job/<city>/<slug>-<R0006xxx>`.
- Details page: Apply is `<a role="button" data-automation-id="adventureButton">`
  (NOT `data-automation-id="applyButton"` — that selector does not exist here).
- After Apply: `[role="dialog"]` contains "Start Your Application" + buttons
  with `data-automation-id` = `autofillWithResume` | `applyManually` |
  `useMyLastApplication` | `closeButton`.
- Choosing autofill → `/apply/autofillWithResume` SPA route.

## 2. The application is an SPA — step detection

The URL does NOT change between steps. Detect the current step from the
progress rail text:

```
completed step N of 6 / current step N of 6
<Step Name>
```

Regex: `current step (\d) of 6\s*\n\s*([^\n]+)`. Steps: Autofill with Resume →
My Information → My Experience → Application Questions → Voluntary Disclosures
→ Review.

## 3. Step 1 — Autofill with Resume

- `input[type=file]` exists (hidden), hydrates lazily — wait/poll up to ~25 s.
- `set_input_files()` triggers upload + resume parse.
- Upload lifecycle visible in body text: `<filename> loading` →
  `<filename> successfully uploaded` + "Successfully Uploaded!". Poll body text
  for `"loading" not in text and filename in text` (max ~90 s), plus 2 s settle.
- Next: `[data-automation-id="pageFooterNextButton"]` (also matches plain
  `button:has-text("Next")`; on Review this SAME daid renders "Submit").

## 4. Step 2 — My Information

- Autofill from the resume lands asynchronously after Next — poll
  `#name--legalName--firstName` until non-empty (up to ~60 s). Observed parse:
  Given="Raval", Family="Meetkumar" (SWAPPED vs. intended), email
  ravalmeett@gmail.com, City Essen, phone `+49 155 6546 8731`.
- Text input ids (React-controlled; synthetic native-setter + input/change
  events work):
  `#source--source`, `#name--legalName--firstName`, `#name--legalName--lastName`,
  `#address--addressLine1`, `#address--postalCode`, `#address--city`,
  `#emailAddress--emailAddress`, `#phoneNumber--countryPhoneCode`,
  `#phoneNumber--phoneNumber`, `#phoneNumber--extension`.
- Required-but-empty after autofill: How Did You Hear About Us?, Street,
  Postal Code. Phone format `+49 155 6546 8731` FAILS validation
  ("Enter a valid format for Phone Number"); digits-only `015565468731` /
  `015567018163` PASSES (verified against the live validator).
- "How Did You Hear About Us?" (`#source--source`) is a searchable MULTI-select
  with hierarchical categories:
  - Top level: Events & Campaigns (category), Job Portals (category), KubeCon,
    Other, Personal Contact or referral, Social Media, University portals.
  - "Job Portals" children: Agentur für Arbeit, Google for Jobs, herCareer,
    Indeed, **Mercedes-Benz career portal**, Stepstone.
  - Categories CANNOT be selected themselves — clicking drills down.
  - NO "Career Fair" option exists anywhere.
- Pre-set by autofill: Phone Device Type = Mobile; Country Phone Code = 
  "Germany (+49)" (input-based picker showing "1 item selected, Germany (+49)").
- Input-based pickers have NO `formField-*` wrapper; read their committed value
  by climbing parents from the input until text matches `/items? selected/`.

## 5. Step 3 — My Experience

- Documents section already contains the uploaded resume (same file). Upload
  UI: "Upload a file (5MB max)* / Drop files here / Select files". A cover
  letter is optional; nothing else is required. Just verify + Next.

## 6. Step 4 — Application Questions

- "When is your earliest possible entry date?" = THREE spinbuttons:
  ids end `dateSectionMonth-input` / `dateSectionDay-input` /
  `dateSectionYear-input` (full id:
  `primaryQuestionnaire--<questionHash>-dateSection…-input`).
  - CRITICAL: synthetic value-setters DO NOT take (Review then shows
    "No Response"). Real keyboard events are required.
  - The segments auto-advance; type the full sequence MMDDYYYY into the
    month segment after JS `focus()` (a normal click can fail with "element
    is outside of the viewport"), confirm `document.activeElement`, then
    verify read-back `{'9','30','2026'}`; retry up to 3×.
- Three "Select One" single-select dropdowns (questionHashes observed:
  …1780002, …1b00000, …1b00003 — hash varies per requisition; map fields by
  LABEL KEYWORDS, never by hash):
  - Disability → options: Yes / No / Not specified.
  - Work permit → "Yes, because I am a citizen of a member state of the
    EU/Iceland/Liechtenstein/Norway/Switzerland" | "Yes, I have a work and
    residence permit for Germany, but I am not a citizen of a member state of
    the EU/Iceland/Liechtenstein/Norway/Switzerland" | "No, currently I do not
    have a work permit for Germany". (This was the truncated screenshot
    option — full text above.)
  - Data transfer → "Yes, I agree to the transfer of my data within
    Mercedes-Benz Tech Innovation and thus have the greatest possible chance
    of finding a suitable position for me." | "No, I do not agree …".
- Select One widgets live in `[data-automation-id="formField-<hash>"]`
  containers. Their committed value is read from the container text; "Select
  One" present = unselected. Open them by clicking the inner trigger
  (`[aria-haspopup='listbox']`, `[role='combobox']`, or
  `[data-automation-id='promptAriaInstruction']`) — clicking the container
  does nothing.

## 7. Step 5 — Voluntary Disclosures

- DOB: same dateSection spinbutton mechanics (MM/DD/YYYY).
- Gender / Nationality / Pronoun: Select One pickers with daids
  `formField-gender`, `formField-nationality`, `formField-pronoun`
  (stable, human-readable ids). Gender options include Male / Female /
  (presumably others — only Male was needed); Nationality is a large list
  (India verified); Pronoun options include He/Him/His (verified).
- Terms checkbox: `#termsAndConditions--acceptTermsAndAgreements` — a REAL
  `<input type=checkbox>`; `check()` works; verification error if missing:
  "Error-Yes, I have read and consent to the terms and conditions /
  Field and Value required".

## 8. Step 6 — Review

- Sections echo every entered value (My Information / Documents /
  Application Questions / Voluntary Disclosures / Terms "Yes").
- Unset dates appear as "No Response" — a reliable canary for date failures.
- Errors render as "Errors Found" + `Error-<label>` blocks (validation never
  navigates away).
- Submit = `[data-automation-id="pageFooterNextButton"]` with text exactly
  "Submit" (same daid as Next — ALWAYS assert the text before clicking).
- After successful submit: POST to
  `/wday/cxs/mercedesbenztechinnovation/jobapplication/<uuid>/finalize` →
  HTTP 200, then `clientPostData` 302 back to jobs list; page shows a
  thank-you/submitted confirmation; the footer button disappears.

## 9. Workday picker interaction mechanics (the hard part)

The single most fragile area. Verified working recipe:

1. **Open**: click the trigger (input for search pickers, inner trigger for
   Select One). Wait for `[role=option]` elements with `offsetParent !== null`
   (up to ~6 s). A stale invisible popup overlay can intercept clicks —
   pre-close with Escape + retry, or `force=True`, or JS focus fallback.
2. **Hover**: real `page.mouse.move` to the option's bounding-box center —
   the virtualized list needs a genuine pointer position.
3. **Click**: JS-click the option's INNER div
   `[data-automation-id="promptLeafNode"]` (React handler lives there;
   a plain Playwright click on the `role=option` element is unreliable).
   Find the option inside ONE `evaluate` call (element handles go stale).
4. **Verify**: the option's `aria-label` flips from `<text> not checked` to
   `<text>, press delete to clear value.` — and for Select One widgets the
   formField area text shows the chosen value (no "Select One").
5. **Commit/close**: `Tab` commits and closes. **NEVER Escape** — Escape
   reverts uncommitted picker selections (verified: selection present in the
   open dropdown, gone after Escape). A body click away also commits.
6. For hierarchical pickers, click the category to drill down, then select
   the leaf; categories themselves are not selectable.
7. Escape IS safe (and useful) when the dropdown is closed, to dismiss stale
   overlay artifacts.

## 10. Environment

- Python 3.13 + Playwright (Chromium 151) — `pip install playwright` +
  `playwright install chromium`.
- Viewport 1440×1000 worked for everything (popup overlays included).
- Headless works identically to headed for the full flow; use headed for
  observation runs.
- Cookie banner: only on portal entry pages; "Accept Cookies" button.
- Site language: English UI (job descriptions partly German).

## 11. Error-message formats (for parsers)

- Required: `The field <name> is required and must have a value.`
- Phone: `Enter a valid format for Phone Number.`
- Checkbox: `Field and Value required`
- Errors Found banner + `Error-<label>` blocks; `aria-invalid=true` on the
  offending control; `[data-automation-id*=error i]` markers exist.

## 12. Known non-issues / traps

- `button[data-automation-id="applyButton"]` — does not exist on this tenant
  (the Apply link is `adventureButton`).
- `input[data-automation-id="fileUploadInput"]` — does not exist; the upload
  input is a plain hidden `input[type=file]`.
- Waiting for `networkidle` is unreliable — Workday streams telemetry
  constantly; treat it as best-effort, rely on DOM states instead.
- The default 30 s locator timeout is too short for popup-overlay retries;
  use short explicit timeouts (5 s) inside retry loops.
- Review-page verification must be label-keyword based (question hashes differ
  per requisition).
