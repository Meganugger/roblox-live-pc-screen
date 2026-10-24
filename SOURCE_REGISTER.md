# SOURCE_REGISTER.md — Every researched source

Statuses: **Discovered** · **Accessed** · **Read** · **Source code inspected** · **Independently tested** ·
**Unavailable** · **Requires further investigation**. A repository is never "inspected" because it appeared in search.

| ID | Name | URL | Category | Accessed | Status | Read / inspected | Useful info | Limitations | Findings | More research? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-0001 | Roblox Creator Docs — `EditableImage` class reference | https://create.roblox.com/docs/reference/engine/classes/EditableImage (source: `Roblox/creator-docs` `content/en-us/reference/engine/classes/EditableImage.yaml` @ `4e795e6`) | Official documentation | 2026-10-24 | Read | Full YAML (class description, all members) | F-0001…F-0004 | Docs, not runtime-tested; no numeric memory budget | F-0001–F-0004 | Runtime test in Studio + published (owner) |
| S-0002 | Roblox Creator Docs — `AssetService` class reference | https://create.roblox.com/docs/reference/engine/classes/AssetService (source YAML @ `4e795e6`) | Official documentation | 2026-10-24 | Read (Editable* methods) | `CreateEditableImage`, `CreateEditableImageAsync`, `CreateEditableMesh*` | Creation API, nil on budget exhaustion | — | F-0001, F-0004 | No |
| S-0003 | Roblox Creator Docs — `Content` datatype reference | https://create.roblox.com/docs/reference/engine/datatypes/Content (source YAML @ `4e795e6`) | Official documentation | 2026-10-24 | Read | Description + constructors | EditableImage does not replicate | "will be replaced … in the future" — recheck periodically | F-0005 | Recheck if Roblox ships replication |
| S-0004 | Roblox Creator Docs — `ImageLabel` class reference | https://create.roblox.com/docs/reference/engine/classes/ImageLabel (source YAML @ `4e795e6`) | Official documentation | 2026-10-24 | Read (Image* properties) | `ImageContent`, `ResampleMode`, `ScaleType` | Display path for EditableImage | — | F-0006 | No |
