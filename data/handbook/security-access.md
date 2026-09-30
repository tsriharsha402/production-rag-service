# Security and Access

These rules protect our customers' data and our systems.

## Authentication

All company systems use single sign-on (SSO). A hardware security key is required as the second factor; SMS codes are not accepted.

## Production access

Nobody has standing access to production. Engineers request just-in-time access through the access portal, the request is approved by the on-call lead, and access expires automatically after 4 hours. Every production session is logged.

## Secrets

Secrets live in the company vault. Never commit secrets, API keys or credentials to source code, and never paste them into chat. If a secret is exposed, rotate it immediately and report it to the security team.

## Access reviews

Managers review their team's access to systems every quarter and remove anything that is no longer needed.

## Devices

Company laptops must use full-disk encryption and lock after 5 minutes of inactivity. Report a lost or stolen device to security@northwind.example within 1 hour.

## Phishing

Forward suspicious emails to security@northwind.example and do not click links in them.
