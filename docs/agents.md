# Agents and scripts

An agent (Claude Code, Claude Desktop, any MCP client) or a script can do
everything a person does on the Process and Batches screens: create batches,
upload images, trace, run auto mode, save and edit results, set treatments,
and get the report and the comparison as JSON.

Two ways in, with the same API key and the same permissions:

- **MCP** at `<server>/mcp`. The Account screen's MCP card gives the setup
  line for each client and makes the key.
- **REST** at `<server>/api/...` with `Authorization: Bearer <key>`. No CSRF
  token is needed with a key. `GET /api/openapi.json` lists every route.

A key acts as its account, never above the key's own scope. A user key gets
the blinded view, exactly as in the browser: no original names, no
treatments. An admin key gets the admin tools too (treatments, translations,
assignment, folders, the comparison). Some things a key can never do, because
they need a browser session: making keys, accounts or links, deleting a batch
or a folder, resetting a whole batch, opening a folder on the server's disk,
and sending a run to a MATLAB helper.

## A typical run

1. **Hash the files** on your side: sha-256 of each file's bytes, plus its
   size, its name and its path inside the folder (`rel`).
2. **`create_batch_from_files`** with `{name, files: [{name, rel, sha, size}]}`.
   Files become images as they do in the browser:
   - `<cell>.tif` is the raw image and `<cell>.tif - Processed method 2.5.tif`
     its processed one;
   - a `.czi` is an image of its own;
   - `*_zNNN.tif` slices become Z-stacks when you pass `stack`.

   The answer lists `missing` (the files the server doesn't have yet) and
   `upload`, which says how to send them.
3. **Upload each missing file** over REST. The bytes never go through MCP,
   whose requests are limited to 1 MiB:
   ```bash
   curl -sS -X POST "$SERVER/api/ais/files" \
     -H "Authorization: Bearer $AIS_KEY" \
     -H "Content-Type: application/octet-stream" \
     --data-binary @"cell1.tif - Processed method 2.5.tif"
   ```
   The answer's `sha256` must match the one you listed. `upload_instructions`
   with `batch_id` lists what is still missing, and `files_stored` checks
   shas.
4. **Run auto mode.**
   - `start_auto_run {batch_id}` runs it over every included image the
     server holds. Images that already have AIS or a done mark are skipped
     unless `skip_done: false`. Each AIS the filters keep is saved, as the
     browser's review "all" saves it.
   - Poll `get_auto_run {run_id}` until `state` is `finished`; it can also
     end `stopped` or `failed`.
   - `general` and `settings` change the method and filters (see
     `auto_defaults`), for example `{general: {auto_method: "fitted2"}}`.
   - `cancel_auto_run` stops a run after the image it is on.
   - The Batches screen shows the run's progress like a browser's.
5. **Or review image by image.**
   - `detect_image {batch_id, image}` gives the candidates the filters keep
     (with `include_hidden`, the others too). Each comes with the `row` to
     save.
   - Save the ones you choose with `save_result {batch_id, image, row,
     client_id}`.
   - `trace_click {batch_id, image, click: [x, y]}` traces from a point, like
     a click.
   - `get_image {sha}` shows you the image.
6. **Export.**
   - `export_report {batch: "12"}` (or `"12,13"` or `"all"`) gives the report
     as JSON: summary, images, assignees, ais, measurements and
     measurement_types; admins also get original_names, by_treatment and
     statistics.
   - `compare_batches {batch_ids: [12, 13]}` (admins) gives the comparison as
     JSON: culture_means, treatment_summary, statistics with Holm-corrected
     p and stars, all_values and original_names.

## The JSON exports

Each sheet is `{"columns": [...], "rows": [{column: value}]}`, holding the
same numbers as the workbook. The browser's report.xlsx is built in the page,
and tests/test_agents.py checks this JSON against that code. It differs from
the workbook only where a program is better served:

- dates are ISO 8601 (UTC);
- an image's `state` is its key (`done`, `auto`, `accepted`, `waiting`,
  `duplicate`, `not_uploaded`);
- a line with no type, or a group with no treatment, is `null`, not
  "(no type)" / "(no treatment)";
- measures are ids (`ais_length`, `ais_soma`, `type:<name>`).

The REST routes behind them:

| What | Route |
|---|---|
| Report | `GET /api/ais/report?batch=<id>[,<id>...]\|all&everything=0\|1&unblind=0\|1&sheets=summary,ais` |
| Comparison (admins) | `POST /api/ais/compare` with `{batch_ids, tests?, units?, sheets: true, plots?: false}` |
| Auto run | `POST /api/ais/batches/{id}/auto`; `GET /api/ais/auto/{run_id}`; `POST /api/ais/auto/{run_id}/cancel`; `GET /api/ais/auto?batch=<id>`; `GET /api/ais/auto/defaults` |

## Notes

- **Auto runs**:
  - The browser's Settings live in its own storage, so a server run uses the
    defaults (`auto_defaults`) unless you pass your own.
  - Runs go one at a time on one worker, with one run per batch.
  - Runs are held in memory: a restart ends them, though what they saved
    stays.
- **Retries**: give `save_result` and `add_measurement` a `client_id` (8 to 64
  letters, digits or `-`). Sending the same one again finds the first row
  instead of adding a second.
- **Deletes**: `delete_result`, `delete_measurement` and (admins)
  `reset_batch_auto` are the only deletes, and are marked destructive so a
  client asks first. Run `export_report` (or, for admins, `get_backup`)
  before a reset.
- **Edits**: `update_result`, `set_result_soma` and `update_measurement` take
  `expect`, the rev you last saw. If someone changed the row since, the call
  is refused with its current state.
