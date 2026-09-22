# CSA template structure reference

Template: `CSA Template/CSA_Template_v<highest>.dotx` (v1.1 at time of writing). Its own `README.md` is the human guide; this file is the agent-facing map. Stable-ID prefixes below are illustrative: the framework numbers headings by ordinal position **with a +1 offset at every level** (Document Control is `@H2`, not `@H1`), so always resolve IDs with `lookupStableId`, never from these numbers.

## Section skeleton (every H1 is a framework "Section N" and starts a new page)

| Section N | Heading 1 | Content |
| --- | --- | --- |
| cover | (no heading; IDs `@H0-...`) | Title, subtitle, banner, four-line block. All from document properties. Do not edit through change records. |
| - | Table of Contents | Live field inside a content control; not in the stable-ID manifest. Refreshed in Word (Ctrl+A, F9). |
| 1 | Document Control | 1.1 Document Information (Field/Details, 7 rows from properties); 1.2 Revision History & Approvals (Version, Date, Author, Description, Approved By); 1.3 Document Map (4 standard rows). |
| 2 | Executive Overview | 2.1 Executive Summary: three placeholder paragraphs, then figure placeholder, caption (`Figure n:`), source line. |
| 3 | Requirement Domain Assessments | 17 domain blocks (3.1 to 3.17), see below. |
| 4 | Migration Discovery | Intro sentence, then 4.1 Installed Applications, 4.2 Failover and Replication Behaviour, 4.3 Patch and Update Tooling, 4.4 Group Policy Observations, 4.5 File Transfer and Local Storage; one placeholder bullet each. |
| 5 | Appendix A: Glossary and Acronyms | Term / Definition table, 10 standard terms pre-filled. |
| 6 | Appendix B: Workstation and Server Discovery Coverage | Host / Role / Discovery Script Run / Notes; 3 placeholder rows. |

Appendices are Heading 1 paragraphs using the "Appendix A:" list (numId 3), so the framework counts them as Sections 5 and 6.

## Domain block (repeated for 3.1 to 3.17)

1. Heading 2 = domain name.
2. Requirement table (CSA Table, 4 columns: Req ID | Requirement | Current State | Rating). Req ID and Requirement are the OT35 checklist text; only Current State and Rating are written. Row IDs are `@H..-T1-R2` and up (R1 is the header).
3. Heading 3 "Discovery Information": two placeholder bullets (style List Bullet). 3.1 adds a "Hosts and roles found" label and a 3-column table (Host(s), Environment, Role); 3.2 adds an "Accounts, groups and service accounts found" label and a 4-column table (Account / Group, Type, Host(s), Purpose / Role). Both tables have two placeholder rows.
4. Heading 3 "Drawbridge Impact": one placeholder paragraph.

| Domain | Name | Requirements (Req ID) |
| --- | --- | --- |
| 3.1 | General / Asset Inventory | SEP-GEN-01, SEP-GEN-03 |
| 3.2 | Identity & Authentication | SEP-ID-01, SEP-ID-02, SEP-ID-03 |
| 3.3 | PKI / Certificates | SEP-PKI-01, SEP-PKI-02 |
| 3.4 | Time Synchronisation | SEP-TIME-01 |
| 3.5 | DNS | SEP-DNS-01 |
| 3.6 | Network / Segmentation | SEP-NET-01, SEP-NET-02, SEP-NET-03 |
| 3.7 | Storage & Data Transfer | SEP-STOR-01, SEP-STOR-02, SEP-STOR-03 |
| 3.8 | Management & Administrative Access | SEP-MGT-01, SEP-MGT-02 |
| 3.9 | Monitoring & Logging | SEP-MON-01, SEP-MON-02, SEP-MON-03 |
| 3.10 | Patch & Lifecycle Management | SEP-PATCH-01, SEP-PATCH-02 |
| 3.11 | Backup & Recovery | SEP-BAK-01, SEP-BAK-02 |
| 3.12 | Isolation & Resilience Validation (“Drawbridge”) | SEP-ISO-01, SEP-ISO-02 |
| 3.13 | Perimeter / Firewall & Network Boundary Validation | SEP-PERIM-01, SEP-PERIM-02, SEP-PERIM-03 |
| 3.14 | Vulnerability Management | SEP-VULN-01, SEP-VULN-02 |
| 3.15 | Infrastructure Dependencies (Virtualisation / Hardware) | SEP-INFRA-01 |
| 3.16 | Supply Chain & Third-Party / Vendor Access | SEP-SUPPLY-01 |
| 3.17 | Internet Access & Communications (Proxy / SMTP) | SEP-INET-01, SEP-INET-02 |

## Placeholder conventions

- Every placeholder is `[bracketed]`. In table cells it is also grey (character style Placeholder Text). In body paragraphs and bullets it is plain text, because the framework copies the first run's formatting when it replaces a paragraph, and grey would carry over into the new text.
- The Rating cell starts as a dropdown content control showing `[Choose a rating]`. Filling it through the framework replaces it with plain text in the Table Rating style; that is expected. Valid values: `Met`, `Partially Met`, `Not Met`, `Not Applicable`.
- The figure placeholder is a bordered paragraph (style Figure) followed by Caption (with a SEQ field) and Figure Source paragraphs.

## Styles (all others are errors in `check_csa.py`)

Paragraph: Normal, Title, Subtitle, Heading 1-3, TOC Heading, TOC 1-2, List Bullet, Label, Table Text, Table Header, Table Rating, Table Gap, Figure, Caption, Figure Source, Cover Block, Header, Footer, plus Word's comment/footnote styles. Character: Placeholder Text, Hyperlink, Comment Reference. Table: CSA Table (orange header row F79646 with white Arial bold 9 pt, banded FDE9D9, black thin borders), CSA Cover Block (dark grey block 3E3E48). Fonts: Arial for headings, Calibri 10 pt body, tables 9 pt.

## Document properties (File > Info > Properties > Advanced > Custom)

`CSA_SystemName` (cover subtitle, cover block, page header, 1.1 title), `CSA_Date` (cover block, revision row; dd/mm/yyyy), `CSA_Version`, `CSA_Status`, `CSA_PreparedFor`, `CSA_PreparedBy`, `CSA_Project`, `CSA_ReferenceStandard` (also cover "Aligned to"). `new_csa.py` sets them and rewrites every field's cached text; changing one later means editing the property in Word and pressing Ctrl+A, F9.

## Guidance comments

The template carries 14 Word comments by author `CSA Template` (contents list, cover/properties, 1.1, 1.2, 2.1, Section 3, first requirement table, Discovery Information, hosts table, accounts table, Drawbridge Impact, Section 4, Appendix A, Appendix B). `new_csa.py` removes them by default; `check_csa.py --final` fails if any remain.

## What the framework can and cannot do to a template CSA (tested 21 Sep 2026, Python 3.10 on Linux, framework as vendored)

Works, and keeps styles: replace a requirement row's Current State and Rating (`Observed:` / `Assessment:` lines, positional columns 3 and 4); replace a whole table row with a pipe row; replace a placeholder bullet or paragraph (List Bullet style and numbering are kept; tracked change); prepareDocument and lookupStableId (appendices resolve as Sections 5 and 6).

Does not work or loses formatting: `Replace the table content` cannot target a table by stable ID (BLOCKED: "Could not locate table caption"); a multi-bullet `Text:` block (`- a` / `- b`) creates List Paragraph paragraphs **without** bullet numbering, and a leading `- ` can survive as literal text; `Insert after` a bullet creates a plain paragraph with no bullet. Adding or removing table rows, bullets, headings or sections is out of the framework's scope. Hence `scaffold_csa.py`: set the number of placeholder rows/bullets first, then replace each placeholder by ID.

Track changes: framework edits to paragraphs are tracked insertions/deletions; table-cell edits are direct replacements. Both are normal; `csa-change-cleanup` accepts revisions later.
