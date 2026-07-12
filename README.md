# Zoho SDK

Decoupled SDK for Zoho API services including Books, Inventory, Creator,
Analytics, WorkDrive, Mail, Cliq, and Sheet.

## Installation

Install locally in editable mode:
```bash
pip install -e .
```

## Configuration

This SDK does not load credentials from local files or environment variables. Credentials must be passed explicitly to the constructors.

Tokens are never persisted by the SDK. `HttpTokenProvider` retrieves tokens at
runtime from a configured HTTP token broker and keeps no token cache. Its
representation is redacted, and callers should never log token values or
authorization headers.
