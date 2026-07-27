# Command contract

Machine output uses `kernform.command/v2` with these required fields:

- `schema`
- `command`
- `status`: `success`, `failure`, or `refused`
- `exit_code`
- `result`
- `diagnostics`
- `artifacts`

Exit classes are stable:

| Code | Meaning |
|---:|---|
| 0 | Success |
| 1 | Invalid command usage or input shape |
| 2 | Conformance or validation failure |
| 3 | Missing dependency or environment failure |
| 4 | Internal execution failure |
| 5 | Policy refusal or unsafe requested mutation |

Human text is not a machine contract. JSON keys, diagnostic IDs, exit classes, and artifact fields
are. NUON output represents the same values without extra decoration.
