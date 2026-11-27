# idealo MCP: what it really returns

> Filled in by the `data-scout` subagent on hackathon day (`/idealo-connect`).
> Until then, nothing in the code may assume a tool name or field.

| Tool | Parameters | Fields we use | Notes |
|---|---|---|---|
| _search_ | | product id, name | |
| _price history_ | | date, price; range and granularity | |
| _offers_ | | merchant, price, shipping, availability | |

## What the SPEC needs and whether the data has it
- [ ] Daily lowest price for at least 90 days
- [ ] Current offers per merchant
- [ ] Availability per merchant
- [ ] A shop's own crossed-out "was" price (probably not available: the shopper enters it)

## Recorded fixtures
`tests/fixtures/idealo/<tool>.json`, one trimmed response per tool. Protected from hand edits by
`.claude/hooks/protect-files.sh`: re-record instead.
