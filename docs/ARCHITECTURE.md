# Discord Config Manager — architecture notes

> This is a **suggested technical boundary for a private-source module**, not a claim that all components are implemented or active in a particular deployment.

## Objective

Operational settings that live in JSON/JSONC files are easy to change incorrectly. A staff interface can offer validated edits, backup-before-write behavior and clear permission boundaries without disclosing raw configuration to all moderators.

## Conceptual responsibilities

**1. Authorized staff.** Choose an authorized configuration source and setting.

**2. Config selector.** Validate the staff identity and restrict sensitive fields.

**3. Validation / redaction.** Parse and validate the proposed value against its schema.

**4. Backup and write.** Create a recoverable backup before applying the change.

**5. Reload status / audit.** Write safely and report whether a restart or refresh is necessary.

## Review risks and recommended tests

| Concern | Failure mode | Verification to add |
|---|---|---|
| Secret leakage | Config files may include tokens or webhooks | Redact values and deny sensitive paths |
| Concurrent edits | Two staff changes can overwrite each other | Use version checks or atomic read-modify-write |
| Corrupt writes | Partial changes can make a bot fail at startup | Use backup and atomic replacement |
| Runtime drift | A saved value may not be loaded into a running service | Report restart/reload state explicitly |

## Integration and permissions

The Discord interaction layer should treat its inputs as untrusted. A server-side handler must establish the principal, check authorization for the concrete operation and return user-safe errors. The persistence or external API adapter is separately responsible for safe updates, retries and recovery. The public `src/public_interface.py` is only a surface sketch; **none of these safeguards can be confirmed by running it**.

## Production/public boundary

No real member IDs, credentials, channel IDs, private schemas, moderation rules or live logs should appear in this repository. The architectural context belongs to the wider [DeadCity platform case study](https://github.com/Scumbagsss/BOT). For a separately developed runnable example, see the [ticket workflow backend](https://github.com/Scumbagsss/advanced-discord-ticket-bot).
