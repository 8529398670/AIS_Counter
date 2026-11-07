# Z-stacks

A Z-stack comes from ZEN's Image Export as a folder of per-slice TIFFs, such as
`IP-ApoTome-04_z01c1+2.tif` to `z11c1+2.tif`. The app keeps it as one image and
measures each AIS through the slices.

Nothing here has been checked against an AIS measured by hand in 3D. The tests
use synthetic stacks with known paths. Until someone has compared a handful of
real AIS with ZEN or ImageJ, treat 3D lengths as unvalidated.

## What the files do and don't carry

- **No calibration.** There is no pixel size or z step in the files, and the
  96 dpi tag is a placeholder. Both are entered when stacks are added and are
  kept with the stack. A wrong z step scales every 3D length.
- **Two real channels.** Red and green are separate stains. Blue is green's
  display tint. Which one marks the AIS varies by batch, so the dialog asks
  every time and remembers nothing.
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

`Trace, then lift to Z` (`zlength.lift`) runs after `run_click`, which is
unchanged:

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

**Compare `length_3d_um` with `length_xy_um`, never with `length_um`.**
`length_um` counts the rounded pixels a trace crosses, which reads above true
length on a diagonal, so a 3D length can come out shorter than it.

`length_um` stays on every row, unchanged. The report's mean, median and spread
still come from it, including on stacks. `soma_um` is an XY distance.

## Known limits

- The AIS start and end come from the projection's intensity profile, where
  out-of-focus signal can shift them.
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

- **CZI Z-stacks.** Waiting on a sample. `czi.py` refuses Z>1 until then. It would
  read into `Library.stack`, with calibration from the file and no dialog fields,
  and would also give 16-bit data with separate channels. Update
  `tests/test_czi.py`.
- **Correcting a z step on saved rows.** `z_path` is stored, so 3D length can be
  worked out again without re-clicking. Nothing does this yet. Until then, re-add
  the stack with the right value and re-click.
- **Tune auto mode for stacks.** It needs hand-clicked stacks as ground truth.
- **AIS bounds along the lifted path.** Sample the intensity profile along the 3D
  route instead of the projection, which would remove out-of-focus signal from
  the start and end.
