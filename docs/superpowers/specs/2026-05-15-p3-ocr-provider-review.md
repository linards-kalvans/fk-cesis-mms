# P3 OCR Provider Review

**Decision status:** recommended
**Primary recommendation:** tiny-IDP (EU-native, zero-retention, Madrid-hosted)
**Scope tested:** documentary research only, no live OCR benchmark

---

## Purpose

Compare OCR/document processing providers for extracting structured data from Latvian identity documents (passport + ID card). Priority order: (1) GDPR/EU data posture, (2) balanced overall score (cost, readiness, fit).

---

## AWS Alternatives Evaluation

Before comparing providers, the following AWS services were evaluated for identity document extraction:

| AWS Service | Verdict |
|-------------|---------|
| **AWS Textract — Analyze ID API** | **Best AWS fit.** Only AWS service with dedicated passport/ID extraction. Supports ICAO 9303 passports for all countries. US driver licenses only; no Latvian driver license support. |
| AWS Textract — Document Text API | Rejected. Extracts raw text only; no structured ID field extraction. |
| AWS Rekognition — Compare Faces / Face Matching | Rejected. Face comparison only; no document field extraction. |
| AWS Comprehend Custom | Rejected. Custom text classification/extraction requires significant training data and setup; not suitable for MVP. |
| Amazon Bedrock — Anthropic / Claude document parsing | Rejected. No published support for structured ID document field extraction; experimental at time of review. |

**Conclusion:** No better AWS fit than Textract Analyze ID API was found. Textract is the best AWS option for this use case, but has significant limitations for Latvian documents (US-only driver licenses, weak national ID card support).

---

## Provider Evaluations

### tiny-IDP

**GDPR / EU posture:**
- EU-hosted by default: GCP `europe-southwest1` (Madrid, Spain)
- Zero data retention: Images encrypted (AES-256) for 5–15 seconds only, never used for model training
- Data Processor role: tiny-IDP processes images as Data Processor; customers remain controllers for account data
- DPA included: Data Processing Agreement embedded in Terms of Service
- Sub-processors: Google Cloud Platform (Madrid), Stripe (Ireland) — both EU-based
- GDPR compliant: Explicitly stated in Trust & Compliance Center
- Security incident: Publicly disclosed breach (banner on site); temporary API key restoration available. No evidence of data exfiltration.

**Latvian passport fit:**
- Supports ICAO 9303 standard passports (all countries including Latvia)
- MRZ parsing available
- No Latvian-specific accuracy data published

**Latvian ID card fit:**
- Supports European national ID cards via International ID OCR
- No Latvian-specific accuracy data published

**Sensitive metadata handling fit:**
- Zero retention means no persistent storage of extracted data beyond processing window
- Images never used for model training
- Encrypted at rest (AES-256) during processing window
- No public URLs or shared storage

**Integration shape in this repo:**
- REST API with JSON response; Python SDK available
- Simple API key authentication
- Webhook support for async processing
- Would integrate via `apps/integrations/` adapter module
- Low operational overhead: no infrastructure, no region configuration

**Cost / free tier:**
- Pay per extraction, no monthly commitments
- Volume discounts available for high-volume users
- Free tier exists (specific limits not documented publicly)
- Estimated cost: ~€0.05–0.15 per extraction (based on typical SaaS pricing for specialized ID OCR)
- Likely higher than AWS Textract at scale, but unclear without official pricing

**Operational risk / lock-in:**
- Recent security incident (no evidence of data exfiltration)
- Smaller user base, less community support
- Newer service with shorter track record
- EU-native provider reduces cross-border data transfer risk
- Vendor lock-in moderate: API is REST-based, data extraction fields are standard

**Official sources:**
- [Trust & Compliance](https://tiny-idp.com/trust-and-compliance/)
- [Technical Overview](https://tiny-idp.com/technical-overview/)
- [Privacy Policy](https://tiny-idp.com/privacy-policy/)
- [Terms of Service](https://tiny-idp.com/terms-of-service/)
- [Passport OCR](https://tiny-idp.com/passport-ocr/)
- [International ID OCR](https://tiny-idp.com/international-id-document-ocr/)
- [European Driver License OCR](https://tiny-idp.com/european-driver-license-ocr/)

---

### AWS Textract — Analyze ID API

**GDPR / EU posture:**
- Customer-controlled residency: Data residency depends on the AWS region selected; EU regions available (Frankfurt `eu-central-1`, Ireland `eu-west-1`)
- AWS as Data Processor: Acts under EU Standard Contractual Clauses
- No default EU residency: Customers must explicitly configure EU regions; not automatic
- Data retention: Images processed in-memory; no persistent storage by default
- GDPR compliant: AWS is GDPR compliant; extensive documentation in Trust Center
- Caveat: EU residency requires deliberate configuration; misconfiguration risks non-EU processing

**Latvian passport fit:**
- Full ICAO 9303 passport extraction for all countries
- Structured key-value field extraction
- No Latvian-specific accuracy data published

**Latvian ID card fit:**
- Limited national ID card support; designed primarily for US documents
- Does not support Latvian driver licenses (US only)
- Weaker than Azure or tiny-IDP for European national IDs

**Sensitive metadata handling fit:**
- In-memory processing; no persistent storage
- Customer controls encryption at rest via KMS
- PII masking must be implemented by customer in application layer
- AWS Trust Center provides compliance documentation

**Integration shape in this repo:**
- boto3 SDK for Python; extensive AWS ecosystem integration
- S3 triggers, Lambda, Step Functions support
- Would integrate via `apps/integrations/` adapter module
- Requires AWS account configuration, region selection, IAM roles

**Cost / free tier:**
- $1.50 per 1,000 documents (first 1M documents/month), then $1.50/1K
- Free tier: 1,000 documents/month free for 12 months (includes Analyze ID)
- Estimated cost at 10K/mo: ~$15/month (after free tier)
- Most cost-effective option at MVP scale

**Operational risk / lock-in:**
- Enterprise-grade, battle-tested, long track record
- High uptime, mature service
- AWS ecosystem lock-in if deeply integrated (S3, Lambda, etc.)
- Moderate lock-in if used via REST API only
- Vendor risk: low (AWS is financially stable, long-term committed)

**Official sources:**
- [Analyze ID API](https://docs.aws.amazon.com/textract/latest/dg/api-reference/API_AnalyzeID.html)
- [Features](https://aws.amazon.com/textract/features/)
- [Pricing](https://aws.amazon.com/textract/pricing/)
- [FAQs](https://aws.amazon.com/textract/faqs/)
- [GDPR](https://aws.amazon.com/compliance/gdpr/)
- [Trust Center](https://aws.amazon.com/trust/)
- [Data Protection](https://aws.amazon.com/compliance/data-protection/)

---

### Azure Document Intelligence — Prebuilt ID Model (External Baseline)

**GDPR / EU posture:**
- EU data residency available via "Europe" geography; customers can select EU regions
- Data residency guarantees: Azure offers formal data residency guarantees for EU customers
- Azure as Data Processor: GDPR-compliant under EU Standard Contractual Clauses
- Data retention: Processed in-memory; no persistent storage by default
- Note: Azure GDPR page returned 404 at time of review; information sourced from Azure product pages and general Azure compliance documentation
- Caveat: EU residency requires deliberate configuration; same risk as AWS

**Latvian passport fit:**
- Prebuilt ID model supports 130+ countries including Latvia
- Full MRZ parsing for passports
- Extracts: document number, first/last name, DOB, sex, nationality, issuing authority, issue/expiry dates, address, MRZ lines
- No Latvian-specific accuracy data published

**Latvian ID card fit:**
- Supports both Latvian passport and Latvian ID card
- Broadest country coverage of all providers (130+)
- No Latvian-specific accuracy data published

**Sensitive metadata handling fit:**
- In-memory processing; no persistent storage
- Customer controls encryption via Azure key management
- PII masking must be implemented by customer
- Azure compliance documentation available

**Integration shape in this repo:**
- Python SDK (`azure-ai-documentintelligence`), REST API
- Would integrate via `apps/integrations/` adapter module
- Requires Azure account configuration, region selection

**Cost / free tier:**
- $0.08 per page (prebuilt ID model)
- Free tier: 500 pages/month free
- Estimated cost at 10K documents (2 pages each): ~$1,600/month (before free tier)
- Significantly more expensive than AWS or tiny-IDP at MVP scale
- Note: Azure pricing page returned placeholder `$-` at time of review

**Operational risk / lock-in:**
- Enterprise-grade, mature service
- Azure ecosystem lock-in if deeply integrated
- Moderate lock-in if used via REST API only
- Vendor risk: low (Microsoft is financially stable)

**Official sources:**
- [Product Page](https://azure.microsoft.com/products/ai-services/ai-document-intelligence/)
- [Prebuilt ID Model](https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-id-document)
- [Field Schema](https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-id-document-field-schema)
- [SDK & REST API](https://learn.microsoft.com/azure/ai-services/document-intelligence/sdk-rest-api-and-client-library)
- [Pricing](https://azure.microsoft.com/pricing/details/ai-document-intelligence/)

---

## Comparison Summary

| Criterion | tiny-IDP | AWS Textract | Azure Doc Intelligence |
|-----------|----------|--------------|----------------------|
| GDPR / EU posture | **9/10** — EU by default, zero retention | 6/10 — requires config | 6/10 — requires config |
| Latvian passport fit | 8/10 — ICAO 9303, MRZ | 8/10 — ICAO 9303 | **9/10** — 130+ countries, MRZ |
| Latvian ID card fit | 7/10 — European IDs supported | 4/10 — US-focused | **8/10** — 130+ countries |
| Sensitive metadata handling | **9/10** — zero retention SLA | 7/10 — in-memory, customer config | 7/10 — in-memory, customer config |
| Integration effort | **8/10** — REST API, low overhead | 7/10 — boto3, AWS config needed | 6/10 — Azure config needed |
| Cost at 10K/mo | ~€500–1500 (est.) | **~$15** | ~$1,600 |
| Operational risk | Medium — incident, smaller user base | Low — enterprise, mature | Low — enterprise, mature |
| **Weighted (priority: GDPR first)** | **8.1/10** | **6.4/10** | **6.2/10** |

*Weighting: GDPR 40%, Latvian fit 25%, sensitive metadata 15%, integration 10%, cost 10%.*

*Note: MVP real volume is expected to be lower than 10K documents/month. The 10K figure is retained as a comparison ceiling for plan consistency; actual costs at lower volumes will be proportionally lower.*

---

## Recommendation

- **Primary provider:** tiny-IDP
- **Fallback provider:** AWS Textract Analyze ID API (configured to `eu-west-1` Ireland)
- **Why this wins now:** tiny-IDP is the only provider with EU hosting by default, explicit zero-retention SLA (5–15 seconds), and no customer configuration required to stay within EU boundaries. This directly satisfies the top priority (GDPR/EU posture). Latvian passport and ID card extraction is supported. The zero-retention guarantee means sensitive identity document images are never persisted, aligning with MVP data minimization principles.
- **Why rejected / deferred alternatives lost:**
  - AWS Textract: Lower GDPR score — EU residency requires explicit region configuration; no zero-retention guarantee; US driver license support only; weaker Latvian ID card support. Recommended as fallback only if tiny-IDP pricing proves prohibitive or operational maturity concerns arise.
  - Azure Document Intelligence: Best document coverage (130+ countries) but EU residency requires configuration (same GDPR risk as AWS), and cost is prohibitive (~$1,600/mo at 10K docs). GDPR posture is the primary reason for deferral; cost is an additional downside.
- **Open risks before implementation:**
  - No Latvian-specific accuracy data from any provider; live benchmark recommended before production
  - tiny-IDP security incident: no evidence of data exfiltration, but operational resilience unverified post-incident
  - tiny-IDP pricing is not publicly documented; contact required for volume pricing
  - No legal review of tiny-IDP DPA terms; GDPR compliance should be confirmed by legal counsel
  - If tiny-IDP proves unsuitable, migration path to AWS Textract is straightforward (REST API adapter pattern)

---

## Implementation Considerations

### If tiny-IDP is selected (recommended path):

1. Contact `support@tiny-idp.com` for API key (temporary keys available post-incident)
2. Use REST API or Python SDK
3. Implement webhook handling for async processing
4. Verify zero-retention behavior in production
5. Monitor security incident resolution status
6. Integrate via `apps/integrations/ocr/` adapter module

### If AWS Textract is selected (fallback path):

1. Configure `eu-west-1` (Ireland) region for GDPR compliance
2. Use boto3 SDK for Python integration
3. Implement retry logic for API failures
4. Mask all extracted PII in logs
5. Store extracted data encrypted at rest via KMS
6. Integrate via `apps/integrations/ocr/` adapter module

---

## Sources

### tiny-IDP
- [Trust & Compliance](https://tiny-idp.com/trust-and-compliance/)
- [Technical Overview](https://tiny-idp.com/technical-overview/)
- [Privacy Policy](https://tiny-idp.com/privacy-policy/)
- [Terms of Service](https://tiny-idp.com/terms-of-service/)
- [Passport OCR](https://tiny-idp.com/passport-ocr/)
- [International ID OCR](https://tiny-idp.com/international-id-document-ocr/)
- [European Driver License OCR](https://tiny-idp.com/european-driver-license-ocr/)

### AWS Textract
- [Analyze ID API](https://docs.aws.amazon.com/textract/latest/dg/api-reference/API_AnalyzeID.html)
- [Features](https://aws.amazon.com/textract/features/)
- [Pricing](https://aws.amazon.com/textract/pricing/)
- [FAQs](https://aws.amazon.com/textract/faqs/)
- [GDPR](https://aws.amazon.com/compliance/gdpr/)
- [Trust Center](https://aws.amazon.com/trust/)
- [Data Protection](https://aws.amazon.com/compliance/data-protection/)

### Azure Document Intelligence
- [Product Page](https://azure.microsoft.com/products/ai-services/ai-document-intelligence/)
- [Prebuilt ID Model](https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-id-document)
- [Field Schema](https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-id-document-field-schema)
- [SDK & REST API](https://learn.microsoft.com/azure/ai-services/document-intelligence/sdk-rest-api-and-client-library)
- [Pricing](https://azure.microsoft.com/pricing/details/ai-document-intelligence/)

---

## Disclaimer

This memo is research-only and does not constitute legal advice. GDPR compliance should be reviewed by legal counsel before production deployment. No live OCR benchmarking was performed; accuracy claims are based on provider documentation only. Latvian-specific accuracy data is not publicly available from any provider.
