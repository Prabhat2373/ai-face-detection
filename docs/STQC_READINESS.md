# STQC Software Product Certification Readiness

This document tracks engineering readiness for STQC evaluation. It is not a certificate or a substitute for STQC assessment.

Reference: https://stqc.gov.in/en/software-product-certification

## Product scope

- Product type: offline-first thick-client desktop application
- Platforms: Windows and macOS installers
- Core functions: face detection/recognition, attendance, camera monitoring, unknown-person alarms, local licensing
- Sensitive data: employee identity data, face photos/embeddings, attendance records, snapshots, camera credentials

## Readiness matrix

| STQC quality area | Current position | Evidence still required |
|---|---|---|
| Functional suitability | Core workflows implemented; attendance roles and camera failures require regression coverage | Requirements-to-test traceability and signed test results |
| Performance efficiency | Performance profiles and bounded camera processing exist | CPU/RAM/latency benchmarks on supported low-end devices |
| Compatibility/interoperability | Windows/macOS packaging exists | Version matrix, RTSP/device matrix, antivirus and permission tests |
| Usability/accessibility | Responsive pages and user-facing errors are being improved | Keyboard, contrast, scaling, font, and accessibility test evidence |
| Reliability/availability | Local DB, backups, health checks, restart handling, and logs exist | Fault-injection, recovery, power-loss, corruption, and soak tests |
| Security | License signing, encrypted camera credentials, request limits, and audit work exist | Threat model, dependency scan, penetration/security test report, key-management procedure |
| Portability | Frozen desktop builds are supported | Clean-machine install/uninstall and upgrade/rollback evidence |
| Privacy/data protection | Processing is local by default | Consent, retention/deletion, access control, privacy notice, and biometric-data handling records |

## Required release evidence

1. Versioned requirements and traceability matrix.
2. Test plan covering functional, negative, performance, compatibility, security, privacy, and recovery cases.
3. Build manifest/SBOM and dependency vulnerability review.
4. Data-flow diagram and threat model.
5. Privacy, retention, backup, restore, and incident-response procedures.
6. Signed installer hashes and release/change records.
7. User, administrator, troubleshooting, and deployment documentation.

## Important limitation

Completing this checklist improves readiness but cannot guarantee certification. Final conformity is determined by STQC or its authorized laboratory after formal evaluation.
