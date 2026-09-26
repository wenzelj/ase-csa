---
name: identity-access-analysis
description: Assess current authentication, authorisation, accounts, roles, privileged access, certificates, and remote access for an Operational Technology application.
---

# Identity and Access Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Document separately:

- identity sources and trust relationships;
- interactive user authentication;
- application authorisation and role mapping;
- administrator and privileged access;
- service, database, scheduled-task, integration, and local accounts;
- Multi-Factor Authentication (MFA), Single Sign-On (SSO), certificate, token, and remote-access mechanisms;
- joiner, mover, leaver, credential rotation, recertification, and emergency-access processes;
- account ownership, logging, and known exceptions.

Do not equate an Active Directory (AD)-joined server with application-level AD authentication. Do not claim least privilege, MFA coverage, password rotation, or account ownership without evidence.

Return an access-path table, role/account inventory at an appropriate sensitivity level, current controls, material exposures, and open questions. Avoid reproducing secrets or unnecessary personal information.
