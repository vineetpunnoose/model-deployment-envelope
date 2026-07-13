# Customer Service TTS Demo - Architecture & Plan

## Overview

A demo where customers call an IVR system, and the system speaks their account information (balance, EMI, loan details) using your custom TTS model - all governed by the envelope.

---

## The Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   CUSTOMER          IVR/APP           APIs            ENVELOPE      TTS     │
│                                                                             │
│      📞 ──────────▶ Answer                                                  │
│                        │                                                    │
│      🔊 ◀──────────── "Welcome, press 1 for balance..."                    │
│                        │                                                    │
│      1️⃣ ──────────▶ Customer pressed 1                                     │
│                        │                                                    │
│                        ├──────────▶ GET /balance/CUST001                   │
│                        │                    │                               │
│                        │           ┌────────▼────────┐                     │
│                        │           │    DATABASE     │                     │
│                        │           │  balance: 52450 │                     │
│                        │           └────────┬────────┘                     │
│                        │                    │                               │
│                        │ ◀──────────────────┘                              │
│                        │                                                    │
│                        │  Construct text:                                   │
│                        │  "Your balance is ₹52,450"                        │
│                        │                                                    │
│                        ├─────────────────────────────▶ POST /v1/speak      │
│                        │                                     │              │
│                        │                              ┌──────▼──────┐      │
│                        │                              │  ENVELOPE   │      │
│                        │                              │             │      │
│                        │                              │ ✓ Caller OK │      │
│                        │                              │ ✓ Data OK   │      │
│                        │                              │ ✓ No PII    │      │
│                        │                              │             │      │
│                        │                              │ ┌─────────┐ │      │
│                        │                              │ │ YOUR    │ │      │
│                        │                              │ │ TTS     │ │      │
│                        │                              │ │ MODEL   │ │      │
│                        │                              │ └────┬────┘ │      │
│                        │                              │      │      │      │
│                        │                              │ 📝 Audit    │      │
│                        │                              └──────┬──────┘      │
│                        │                                     │              │
│                        │ ◀────────────────────────── audio.wav             │
│                        │                                                    │
│      🔊 ◀──────────── Play audio                                           │
│                                                                             │
│   Customer hears: "Your balance is ₹52,450"                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Database

Stores customer information:

```
┌─────────────────────────────────────────────────────────────┐
│                      CUSTOMERS TABLE                        │
├──────────┬─────────────────┬────────────────┬──────────────┤
│ id       │ name            │ phone          │ account_no   │
├──────────┼─────────────────┼────────────────┼──────────────┤
│ CUST001  │ Rajesh Kumar    │ +91-9876543210 │ 1234567890   │
│ CUST002  │ Priya Sharma    │ +91-9876543211 │ 1234567891   │
│ CUST003  │ Amit Patel      │ +91-9876543212 │ 1234567892   │
└──────────┴─────────────────┴────────────────┴──────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      ACCOUNTS TABLE                         │
├──────────┬───────────┬─────────────┬───────────┬───────────┤
│ cust_id  │ balance   │ loan_amount │ emi       │ next_emi  │
├──────────┼───────────┼─────────────┼───────────┼───────────┤
│ CUST001  │ 52,450    │ 5,00,000    │ 12,500    │ 25-Jan    │
│ CUST002  │ 1,50,000  │ 0           │ 0         │ -         │
│ CUST003  │ 8,500     │ 3,00,000    │ 8,500     │ OVERDUE   │
└──────────┴───────────┴─────────────┴───────────┴───────────┘
```

---

### 2. APIs

Your backend APIs that fetch data:

| Endpoint | Returns | Example Response |
|----------|---------|------------------|
| `GET /api/customer/{phone}` | Customer lookup | `{"id": "CUST001", "name": "Rajesh Kumar"}` |
| `GET /api/balance/{id}` | Account balance | `{"balance": 52450.75}` |
| `GET /api/emi/{id}` | EMI information | `{"amount": 12500, "due_date": "2025-01-25", "overdue": false}` |
| `GET /api/loan/{id}` | Loan details | `{"total": 500000, "remaining": 425000, "emi": 12500}` |
| `GET /api/last-payment/{id}` | Last payment | `{"amount": 12500, "date": "2024-12-25"}` |

---

### 3. Envelope (Governance Layer)

Wraps your TTS with controls:

```
┌─────────────────────────────────────────────────────────────┐
│                        ENVELOPE                             │
│                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │   CALLER    │   │    DATA     │   │   CONTENT   │       │
│  │    AUTH     │   │   CLASS     │   │   FILTER    │       │
│  │             │   │             │   │             │       │
│  │ Who can     │   │ What type   │   │ Scan for    │       │
│  │ call TTS?   │   │ of info?    │   │ PII/secrets │       │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘       │
│         │                 │                 │               │
│         └────────────┬────┴─────────────────┘               │
│                      ▼                                      │
│              ┌──────────────┐                              │
│              │  YOUR TTS    │                              │
│              │   MODEL      │                              │
│              └──────────────┘                              │
│                      │                                      │
│              ┌──────────────┐                              │
│              │  AUDIT LOG   │                              │
│              └──────────────┘                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4. Your TTS Model

Already built, running on GPU. The envelope will call it.

---

## Governance Rules

### Who Can Use TTS?

| Caller | Allowed? |
|--------|----------|
| `ivr_system` | ✅ Yes |
| `agent_desktop` | ✅ Yes |
| `qa_testing` | ✅ Yes |
| `external_api` | ❌ No |
| `unknown` | ❌ No |

### What Data Can Be Spoken?

| Data Class | Allowed? | Example |
|------------|----------|---------|
| `greeting` | ✅ Yes | "Welcome to ABC Bank" |
| `balance_info` | ✅ Yes | "Your balance is ₹52,450" |
| `emi_info` | ✅ Yes | "Your EMI of ₹12,500 is due on 25th" |
| `loan_info` | ✅ Yes | "Your loan balance is ₹4,25,000" |
| `account_number` | ❌ No | Account numbers should not be spoken |
| `otp` | ❌ No | OTPs should not be spoken |
| `password` | ❌ No | Passwords should not be spoken |

### Auto-Redaction

If text accidentally contains sensitive patterns, they get redacted:

| Pattern | Example | Spoken As |
|---------|---------|-----------|
| 10+ digit number | "Account 1234567890" | "Account [REDACTED]" |
| SSN pattern | "SSN 123-45-6789" | "SSN [REDACTED]" |
| Email | "email@test.com" | "[REDACTED]" |

---

## Example Conversations

### Scenario 1: Balance Inquiry

```
Customer: *calls*
IVR: "Welcome to ABC Bank. Press 1 for balance, 2 for EMI, 3 for loan details"
Customer: *presses 1*

System internally:
  1. API call: GET /api/balance/CUST001 → {"balance": 52450.75}
  2. Construct: "Your current account balance is ₹52,450.75"
  3. Send to envelope: {text: "...", caller: "ivr_system", data_class: "balance_info"}
  4. Envelope: ✓ All checks pass → generate audio

IVR: 🔊 "Your current account balance is ₹52,450.75"
```

### Scenario 2: EMI Information

```
Customer: *presses 2*

System internally:
  1. API call: GET /api/emi/CUST001 → {"amount": 12500, "due_date": "2025-01-25"}
  2. Construct: "Your next EMI of ₹12,500 is due on 25th January 2025"
  3. Send to envelope
  4. Envelope: ✓ Pass → generate audio

IVR: 🔊 "Your next EMI of ₹12,500 is due on 25th January 2025"
```

### Scenario 3: Overdue EMI

```
Customer: CUST003 *presses 2*

System internally:
  1. API call: GET /api/emi/CUST003 → {"amount": 8500, "overdue": true, "overdue_days": 3}
  2. Construct: "Your EMI of ₹8,500 is overdue by 3 days. Please pay immediately."
  3. Send to envelope
  4. Envelope: ✓ Pass → generate audio

IVR: 🔊 "Your EMI of ₹8,500 is overdue by 3 days. Please pay immediately."
```

### Scenario 4: Blocked Request

```
External system tries to use TTS:

System internally:
  1. Send to envelope: {text: "...", caller: "external_api", data_class: "balance_info"}
  2. Envelope: ❌ DENIED - caller not authorized

Response: 403 Forbidden
```

### Scenario 5: PII Redaction

```
Someone accidentally sends account number:

System internally:
  1. Text: "Your account number is 1234567890 and balance is ₹52,450"
  2. Envelope content filter: Detects 10-digit number
  3. Redacts: "Your account number is [REDACTED] and balance is ₹52,450"
  4. Generates audio with redacted text

IVR: 🔊 "Your account number is [REDACTED] and balance is ₹52,450"
```

---

## Services & Ports

| Service | Port | Purpose |
|---------|------|---------|
| Database | - | SQLite file (or your DB) |
| Customer APIs | 8000 | REST APIs for customer data |
| Envelope + TTS | 8001 | TTS with governance |
| Dashboard | 8080 | Web UI for audit/escalations |

---

## Files We'll Create

```
examples/customer-service-demo/
├── database.py          # Customer data (or connect to your DB)
├── api_server.py        # REST APIs for customer data
├── tts_service.py       # Envelope wrapping your TTS
├── ivr_simulator.py     # Simulate customer calls (for testing)
└── config.yaml          # Governance rules
```

---

## Questions to Answer Before Coding

1. **Database**:
   - Use SQLite for demo?
   - Or connect to your existing database?

2. **Your TTS Model**:
   - How do you call it? (function? class? API?)
   - What parameters does it need? (text, voice, language?)

3. **Languages**:
   - English only?
   - Hindi? Other languages?

4. **Voices**:
   - How many voices do you have?
   - What are they called?

5. **Deployment**:
   - Everything on same GPU server?
   - Or separate machines?

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GPU SERVER                                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐       │   │
│  │   │   Database   │     │  API Server  │     │  Dashboard   │       │   │
│  │   │   (SQLite)   │◀───▶│   (:8000)    │     │   (:8080)    │       │   │
│  │   └──────────────┘     └──────┬───────┘     └──────────────┘       │   │
│  │                               │                     ▲               │   │
│  │                               │                     │               │   │
│  │                               ▼                     │               │   │
│  │                        ┌──────────────┐            │               │   │
│  │                        │   Envelope   │────────────┘               │   │
│  │                        │   (:8001)    │                            │   │
│  │                        │              │                            │   │
│  │                        │ ┌──────────┐ │                            │   │
│  │                        │ │  Gates   │ │                            │   │
│  │                        │ └────┬─────┘ │                            │   │
│  │                        │      │       │                            │   │
│  │                        │ ┌────▼─────┐ │                            │   │
│  │                        │ │ Your TTS │ │  ◀── GPU Memory            │   │
│  │                        │ │  Model   │ │                            │   │
│  │                        │ └──────────┘ │                            │   │
│  │                        │              │                            │   │
│  │                        └──────────────┘                            │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Summary

1. **Database** holds customer info (balance, EMI, loans)
2. **APIs** fetch this data when needed
3. **IVR/App** constructs the text to speak
4. **Envelope** validates and governs the request
5. **Your TTS** generates the audio
6. **Customer** hears the response
7. **Dashboard** shows all activity for audit

All governed by rules YOU configure in the manifest.
