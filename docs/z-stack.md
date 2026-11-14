# Z-stacks

A Z-stack comes either as ZEN's own `.czi` file, holding every slice, or from
ZEN's Image Export as a folder of per-slice TIFFs, such as
`IP-ApoTome-04_z01c1+2.tif` to `z11c1+2.tif`. The app keeps either as one image
and measures each AIS through the slices.

Nothing here has been checked against an AIS measured by hand in 3D. The tests
use synthetic stacks with known paths. Until someone has compared a handful of
real AIS with ZEN or ImageJ, treat 3D lengths as unvalidated.

## CZI Z-stacks

A `.czi` with more than one Z plane is one Z-stack image. The two samples are
`Slide7zstackExperiment-26.czi` (9 slices, 260 MB) and `-27.czi` (11 slices,
318 MB), the originals of stacks 03 and 04 below.

- **Calibration from the file.** The pixel size and z step come from its
  Scaling (0.1024 µm/px and 0.77 µm on both samples, from a 63x/1.40 oil
  objective). There are no fields for them when adding. *Channels…* can still
  correct them later, which gives the stack a new sha, as for TIFF slices. A
  file without Scaling takes the fields TIFF slices use.
- **Separate channels at 12 bits.** Alexa Fluor 594 and Alexa Fluor 488 are
  read as they were recorded, with nothing clipped at 254. They are put on
  the same scale as a 2D `.czi` (times 16), so preprocessing sees what it
  always sees.
- **The AIS channel.** The Channels dialog still opens on every add, with
  Alexa Fluor 488 picked, as for a 2D `.czi` (`channels.ais_index`). Picking
  another channel gives another sha.
- **ApoTome phases.** These files hold ApoTome's raw grid images, not ZEN's
  processed ones: five per slice and channel (the CZI's H dimension), the grid
  moved a fifth of its period each time. The add dialog asks how to make them
  into slices:
  - *Sectioned* (default): `|Σ P_k·e^(−2πik/5)| · 2/5`, the amplitude of the
    grid's modulation, which only in-focus light has. On stack 04 it
    correlates r = 0.99 (488) and 0.94 (594) with ZEN's IP-ApoTome export. ZEN
    also corrects grid phase and bleaching, so it is close to ZEN's, not the
    same.
  - *Widefield*: the mean of the five, in-focus and out-of-focus light
    together (r ≈ 0.56 with the export).

  The choice is part of the stack's sha, so the same file added both ways is
  two images with their own measurements. A `.czi` with no phases skips the
  question.
- **How it is stored.** The `.czi` is the stack's only real file, so uploads,
  exports and backups handle one file. Its manifest
  (`zstack.czi_manifest`) names that file (`source`), the channel (`plane`),
  `apotome` and the calibration, with slices numbered 1 to Z as ZEN numbers
  its exported `z01` files. `czi.read_stack` builds the slices from a mmap of
  the file, one slice and phase at a time: about 0.3 s and 32 MB for stack 04.
  The browser reads Z, H and Scaling from the file's header as it hashes it
  (`Channels.readCzi`), and sends them with the file (`zstack`). Open path
  reads the same from the server's copy (`local.czi_stack_of`).
- **Uploads stream to disk.** An upload is written beside the stored files as
  it arrives and is checked once it is complete (`service.Incoming`), so a
  300 MB file never sits in memory, which matters in the 256 MB container.
  The limit is `server.upload_limit_bytes`, 1 GiB by default. A reverse proxy
  in front has a limit of its own. JSON bodies, such as file lists, backups
  and base64 uploads, stay at 64 MiB.

## What the TIFF exports do and don't carry

- **No calibration.** There is no pixel size or z step in the files, and the
  96 dpi tag is a placeholder. Both are entered when stacks are added and are
  kept with the stack. A wrong z step scales every 3D length.
- **Two real channels.** Red and green are separate stains. Blue is green's
  display tint. Which one marks the AIS varies by batch, so the Channels
  dialog asks every time (no guess for slices) and remembers nothing. The AIS
  channel picked there is the stack's plane; *Channels…* changes it later,
  which gives the stack a new sha (`app/analysis/channels.py`).
- **8-bit display exports.** These are rendered through ZEN's display settings,
  not raw camera data. Bright areas can clip at 254.
- **LZW compression.** `imagecodecs` has no Alpine wheel, so Pillow decodes these
  in Docker (`app/analysis/images.py`).

## How a stack is stored

An image has one file in role `stack`, standing for its slices. Its sha is the
sha-256 of a manifest: the slices in z order, the chosen plane and the
calibration (`app/analysis/zstack.py`). Anything that takes a sha gets the max
projection back, so tracing, previews and thumbnails work as they do for a
`.czi`.

- The batch record is the source of truth. `<sha>.zstack` beside the files is a
  cache, rebuilt from the record if lost or spoiled.
- The sha is not a file, so it can't be uploaded or downloaded. Uploads, exports
  and backups walk the slices (`real_files`, `Ais.parts`).
- Changing the plane or calibration gives a different sha, so re-adding a stack
  with a corrected z step is not treated as a duplicate.
- Blinding hides the stack's folder too, as it is usually named after the
  stack. Slices keep their names at rest and lose them when sent to anyone but
  an admin.

## How length is worked out

Two methods are built, chosen in Settings (Z method).

### Trace, then lift to Z

`zlength.lift` runs after `run_click`, which is unchanged:

1. The existing tracer runs on the projection, giving the trace and the AIS start
   and end.
2. A 3×3 mean is sampled on every slice along the AIS.
3. Each slice is scaled by its own bright level, as end slices are dim.
4. Viterbi finds the brightest route through Z with a cost per slice moved, so a
   fibre crossing at another depth can't take over.
5. A centroid refines z below one slice, and a stiff spline smooths it. XY's
   smoothing value leaves the slice staircase in and adds false length.
6. Arc length is measured along the tracer's spline, with and without z.

| Field | Meaning |
|---|---|
| `length_3d_um` | Arc length along the AIS with z |
| `length_xy_um` | The same section without z |
| `z_start`, `z_end` | Slice numbers at each end, below one slice |
| `z_span_um` | Highest to lowest point, in µm |
| `z_step_um` | The z step this row used |
| `z_confidence` | How far the route stands above the other slices, 0 to 1. A rough guide, not calibrated |
| `z_clipped` | 1 if an end sits on the first or last slice, so the AIS may run out of the stack and the length is a lower bound |
| `z_method` | Which method measured it |
| `z_path` | z at each trace pixel, empty outside the AIS (stored on the row, not in the CSV) |
| `z_ais_start`, `z_ais_end` | Ends from the slices only: the AIS ends it found, as profile points |

### Trace, lift to Z, ends from the slices

`zlength.lift_ends` is an opt-in method. `lift` is unchanged by it. It finds
the AIS start and end again from the slices instead of the projection:

1. A route through the slices along the **whole** trace. This route may climb
   no steeper than 45° (`MAX_SLOPE`): it moves at most one slice per z step's
   worth of XY travel. Slices are levelled by their own bright level, so a
   patch alone in its slice looks as bright as the AIS. `lift`'s free route
   can be drawn onto such a patch past an AIS's end; this one is not.
2. The levelled intensity along that route, at each point's z.
3. The original's own rules on that profile (`zlength._bounds`, a copy of
   `ais_auto.measure`'s): sliding mean, scaled 0 to 1, the last point above
   f after the peak, the last below f before it. A test checks that they
   give `measure`'s own answer on a click's profile.
4. The section between the new ends, measured as `lift` measures its, along
   the same route.

The row gets `z_ais_start` and `z_ais_end`, the new ends as profile points. The
Profile panel then shows the 3D profile. `length_um` and the areas stay the
projection's; the tube volume lays the projection's widths along the new
section, so it is an estimate past the old ends.

**Compare `length_3d_um` with `length_xy_um`, never with `length_um`.**
`length_um` counts the rounded pixels a trace crosses, which reads above true
length on a diagonal, so a 3D length can come out shorter than it.

`length_um` stays on every row, unchanged. The report's mean, median and spread
still come from it, including on stacks. `soma_um` is an XY distance.

## Known limits

- With `lift`, the AIS start and end come from the projection's intensity
  profile, where out-of-focus signal can shift them. *Ends from the slices*
  is the opt-in answer to that, and is not validated either.
- The ApoTome sectioning here is not ZEN's (no grid-phase or bleaching
  correction) and has a small positive noise floor, which `preprocess` and
  the slice levels see as background.
- An AIS running out of the stack is flagged, not corrected.
- The stage's z step can differ from true depth in the sample if the objective's
  immersion doesn't match the mounting medium.
- Auto mode runs on stacks but isn't tuned for them: on the two samples, Fitted
  found 21 AIS-sized candidates out of 307. Click first.

## TODO

### Click ends per slice

Listed in Settings as not built: `zlength.end_clicks`.

- **What:** scroll to the slice where the AIS start is in focus and click, then
  the same for its end. Length is the 3D distance between the two.
- **Where it plugs in:** the Z slider gives the slice. It needs a two-click capture
  on the canvas, modelled on the Measure tool, plus a route that takes both
  points with their z. `Library._lifted` passes a run_click answer today, so this
  method needs its own input.
- **Weakness:** a straight line, so a curved AIS reads short. More clicks per AIS.
- **Validate:** on AIS that are straight in XY, it should agree with
  `length_3d_um`. This makes it a useful check on `lift` even if it is never
  the main method.
- **To enable:** write the function and set `ready` to true in `zlength.METHODS` and
  `Settings.zMethods`.

### Full 3D tracing

Listed in Settings as not built: `zlength.volume_trace`.

- **What:** segment the volume and skeletonize it in 3D, so no projection is
  involved and crossing axons separate properly.
- **Where it plugs in:** it replaces tracing rather than following it, so it needs
  a route of its own. `Library.stack` gives the volume.
- **Weakness:** a new tracer with no ground truth, on structures only a few
  slices deep. `scikit-image` isn't in the server's requirements and would need
  checking for Alpine wheels. `mlcompat`'s primitives are 2D.
- **Validate:** needs AIS traced by hand through the stack first.

### Other

- **Check the sectioning against ZEN** on more stacks, and the 3D lengths of
  a CZI stack against the same AIS on its TIFF export.
- **Re-choose ApoTome after adding.** Today, add the file again the other way.
- **Correcting a z step on saved rows.** `z_path` is stored, so 3D length can be
  worked out again without re-clicking. Nothing does this yet. Until then, re-add
  the stack with the right value and re-click.
- **Tune auto mode for stacks.** It needs hand-clicked stacks as ground truth.
- **Ends from the slices on the fast engine** lays the projection's widths
  along the new section for the tube volume, like the classic engine; neither
  measures the blob past the projection's ends.
