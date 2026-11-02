# The lab's original AIS workflow

How AIS lengths were measured before this app, from the lab's walkthrough
(*AIS_workflow.pdf*), and which steps the app now does.

## 1. Blind the files

Put every `.czi` of the experiment in one folder (*CZIs Random*) together with
the `RandomNames` batch file, and run it. Each file gets a random name such as
`19891-24785-20711.czi`, and `__Translation.txt` records the original names.
Copy that translation file somewhere safe (it is the only way back), then
delete it and `RandomNames` from the folder.

*App:* not done. Open the already-blinded `.czi` files.

## 2. Export the AIS channel from ZEN (Processing > Batch > Image Export)

Load the randomized `.czi`s and choose *Image Export*. Settings:

- TIFF, no compression, *Convert to 8 bit* off, resize 100 %
- *Original Data* on, *Shift Pixel* on; display settings, channel names off
- *Define Subset*, with only the AIS channel (the green AF488 in the
  walkthrough)
- Output folder *Tifs* (not the input folder), naming `%N`
- *Copy Parameters* on the first file, *Paste Parameters* to the rest,
  *Check All* (all green), *Run Selected*

Each file becomes `<name>_c2_ORG.tif` (the ending can differ; the example
data has `_b0c0x0-1388y0-1040_ORG.tif`).

*App:* CZI mode reads that channel straight from the `.czi`. It equals the
export exactly (12-bit values times 16).

## 3. Clean up in Fiji: "Processed method 2.5"

Run the macro [`original-code/AISCleanUpWORKS.ijm`](../original-code/AISCleanUpWORKS.ijm).
*Images to process* is *Tifs*, and *Image destination* is *processed tifs*.
Each output is `<name>_c2_ORG.tif - Processed method 2.5.tif`: the raw image,
with everything but the axon-like structures set to 0.

*App:* `app/analysis/preprocess.py` does this for a `.czi`, identical to
Fiji (README, "Processed method 2.5").

## 4. Measure in MATLAB

Copy both folders' contents into one *MATLAB* folder. Open
`ais_auto_measured.m` and check its pixel size (`pixconv = 0.161` µm per
pixel; ZEN's *Info* lists it per file). Then call it once per image (Run >
*type code to run*):

```matlab
('C:\...\MATLAB\19891-24785-20711_c2_ORG', 0.01, 'gaussian', 0)
```

This is the raw file's path without `.tif`, then threshold 0.01 (raise or
lower it if traces come out wrong), smoothing `'gaussian'`, and chosen `0`.
Click each AIS. The length lands on the clipboard; paste it into Excel if
the smoothed and normalised profile looks reasonable. For the next image,
only the file name changes.

*App:* the **Process** screen is the port of this step (`ais_auto.m`, the
same call). It works on the TIFF pair or the `.czi`, with click, keyboard,
auto mode and server-side results in place of the clipboard and Excel.
