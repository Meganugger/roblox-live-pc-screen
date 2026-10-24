# FINDINGS_LOG.md — Every material discovery

Format per finding: ID · date · research question · approach/query · source (S-xxxx + URL) · what was examined ·
finding · evidence · source type · confidence/limitations · why it matters · effect on architecture · action · related
files/decisions · remaining uncertainty · checkpoint. Labels: **[OFFICIAL]** Roblox docs, **[CODE]** inspected source,
**[COMMUNITY]** forum/Reddit claims, **[TESTED]** independently executed, **[ASSUMPTION]**/**[ESTIMATE]** explicitly.

## Research R1 — Official Roblox API verification (T-0003)

All R1 findings were obtained on 2026-10-24 by downloading the **official Creator Docs source files** from the public
`Roblox/creator-docs` GitHub repository (snapshot `4e795e65a41fd48624fd85442292a81baa6bb3f5`, main branch, committed
2026-10-24T10:11:10Z) with `curl` from `raw.githubusercontent.com`, then parsing the YAML with PyYAML. These files are the
source of the pages on `create.roblox.com/docs` (the rendered page URL is given per source). Label: **[OFFICIAL]**.

### F-0001 — `EditableImage` is the supported runtime pixel API; pixels are written as RGBA8 buffers [OFFICIAL]
- **Question**: §10 Q6/Q7 — can an experience build/modify images from raw pixels at runtime; exact API?
- **Source**: S-0001 (`reference/engine/classes/EditableImage.yaml`), S-0002 (`AssetService.yaml`).
- **Finding**: `AssetService:CreateEditableImage(editableImageOptions: Dictionary?) -> EditableImage` creates a blank
  image (default **512×512**; size set via the options table). `EditableImage:WritePixelsBuffer(position: Vector2, size:
  Vector2, buffer: buffer)` writes a rectangular region; `ReadPixelsBuffer(position, size) -> buffer` reads one. Buffer
  layout: **one byte per channel, 4 bytes per pixel, order R,G,B,A** (alpha, not transparency). Origin is **top-left**
  `(0,0)`, bottom-right `(Size.X-1, Size.Y-1)`. `Size` is read-only, **max 1024×1024**, cannot be resized (create a new
  image + `DrawImageTransformed` to rescale). Other methods: `DrawRectangle/DrawLine/DrawCircle/DrawImage/
  DrawImageTransformed/DrawImageProjected/SampleImageProjected/Destroy` (Destroy "immediately reclaim[s] used memory").
  `WritePixelsBuffer` is `thread_safety: Unsafe`; `ReadPixelsBuffer` is `Safe`. Neither has a security restriction.
- **Evidence**: method signatures and descriptions in S-0001/S-0002 (quoted in `docs/research/ROBLOX_API_FACTS.md`).
- **Confidence**: high (generated from the engine API). **Limitation**: no numeric client memory budget is documented.
- **Impact**: a frame of W×H is reconstructed client-side by writing an RGBA8 `buffer` of W·H·4 bytes (or sub-rectangles
  for changed regions). The decoder must output RGBA8, top-left origin, row-major. Max 1024×1024 per image.
- **Action**: codec (T-0009) targets RGBA8 output + rectangle updates; default stream resolution ≤ 1024 wide.

### F-0002 — Only ONE displayed `EditableImage` is updated per frame [OFFICIAL]
- **Question**: §10 Q7 (restrictions) / performance.
- **Source**: S-0001, section "Update Limitations".
- **Finding**: "Only a single `EditableImage` can be updated per frame on the display side. For example, if you update three
  `EditableImage` objects which are currently being displayed, it will take three frames for all of them to be updated."
- **Impact**: splitting the screen into many EditableImage tiles multiplies display latency and can tear across tiles.
  **Use a single EditableImage per screen** (≤ 1024×1024) and apply changed regions with `WritePixelsBuffer` sub-rects.
- **Action**: architecture constraint for T-0008/T-0012.

### F-0003 — `EditableImage` fails by default in published experiences; an owner toggle enables it [OFFICIAL]
- **Question**: §10 Q12/Q13/Q14 — required settings; Studio vs published.
- **Source**: S-0001, section "Enabling for Published Experiences".
- **Finding**: "For security purposes, using `EditableImage` fails by default in published games. To enable it, open the
  Creator Dashboard, go to the game's **Configure ⟩ Settings**, and toggle on **Enable Mesh / Image APIs**. Alternatively,
  in Studio, open **Experience Settings** and toggle on **Allow Mesh / Image APIs** under **Security**." The page asks the
  creator to review the Terms of Use before enabling.
- **Impact**: mandatory deployment step; the troubleshooting guide must cover "works in Studio, fails when published".
- **Action**: add to deployment checklist (T-0014) and to the client's error state ("Mesh/Image APIs disabled").
- **Uncertainty**: the docs do not list account-level eligibility conditions for the toggle; verify on the owner's
  dashboard during the published test.

### F-0004 — Client-side memory budget; creation returns `nil` when exhausted [OFFICIAL]
- **Source**: S-0001 "Memory Limits"; S-0002 `CreateEditableImage` description.
- **Finding**: "`EditableImage` has strict client-side memory budgets, although the server, Studio, and plugins operate
  with unlimited memory." "If the device-specific editable memory budget is exhausted, creation fails and this method
  returns `nil`." Linking one EditableImage to several Content properties ("multi-referencing") is the recommended memory
  optimisation.
- **Impact**: the client must handle `nil` (show an error state, retry with a smaller resolution profile), reuse one image
  across frames (never create one per frame) and `Destroy()` it on cleanup. **Studio success does not prove the client
  budget holds on low-end devices.**
- **Action**: T-0012 must implement nil-handling + reuse + Destroy; test plan includes a low-memory device test.

### F-0005 — `Content.Object` (EditableImage) does NOT replicate; clients see an unusable placeholder [OFFICIAL]
- **Question**: §10 Q8 — do dynamic image changes replicate?
- **Source**: S-0003 (`reference/engine/datatypes/Content.yaml`), S-0001 (`Size` tagged `NotReplicated`).
- **Finding**: "Replication is not yet supported for `Content.Object` values. When an Instance with a Content property
  containing a Content.Object value is replicated, an unusable placeholder Object of the same type will be used instead
  … any attempt to read or write the contents of that placeholder object will throw. These placeholder objects will render
  as a cyan and magenta checkerboard pattern. … For now, do not use EditableImage or EditableMesh as Content on the server
  on an Instance that can replicate to clients."
- **Impact**: **every client must create and update its own EditableImage locally** (LocalScript). The server can only
  forward frame data (bytes) to clients; it cannot render the image for them. This rules out server-side image
  construction and confirms the "client-side reconstruction" part of the intended architecture.
- **Action**: T-0012 places reconstruction in a client script; server only relays validated frame payloads.

### F-0006 — `ImageLabel.ImageContent` displays an EditableImage; `ResampleMode` controls scaling [OFFICIAL]
- **Source**: S-0004 (`reference/engine/classes/ImageLabel.yaml`), S-0001.
- **Finding**: `ImageLabel.ImageContent: Content` "should hold an asset URI or a reference to an EditableImage object"; set
  it with `Content.fromObject(editableImage)`. `MeshPart.TextureContent` also accepts it. `ImageLabel.ResampleMode`
  (`Enum.ResamplerMode`, e.g. `Pixelated`) controls filtering when the image is scaled; `ScaleType` controls fitting.
- **Impact**: physical screen = Part + `SurfaceGui` + full-size `ImageLabel` whose `ImageContent` is the client's
  EditableImage. Aspect ratio handled by ScaleType/`UIAspectRatioConstraint` (to verify in T-0012).
