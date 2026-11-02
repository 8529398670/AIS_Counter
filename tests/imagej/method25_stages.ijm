// original-code/AISCleanUpWORKS.ijm ("Processed method 2.5") with every
// intermediate saved, for scripts/preprocess_check.py --stages.
//
//   fiji -batch tests/imagej/method25_stages.ijm "IN_DIR|OUT_DIR|LIMIT"
//
// Not --headless: the ROI Manager needs a display (batch mode still opens no
// windows). Reads every *_ORG.tif in IN_DIR (the first LIMIT, 0 = all) and
// writes OUT_DIR/<name>/1-background.tif ... 8-final.tif. The steps are the
// macro's, line for line; only the folder dialogs are replaced. "Black
// background" on (Process > Binary > Options), as in the lab's runs.
args = split(getArgument(), "|");
origin = args[0] + File.separator;
dest = args[1] + File.separator;
limit = 0;
if (args.length > 2) limit = parseInt(args[2]);
lista = getFileList(origin);
setBatchMode(true);
done = 0;
for (j = 0; j < lista.length; j++) {
    if (!endsWith(lista[j], "_ORG.tif")) continue;
    if (limit > 0 && done >= limit) break;
    done++;
    out = dest + lista[j] + File.separator;
    File.makeDirectory(out);
    roiManager("reset");
    open(origin + lista[j]);
    originalTitle = getTitle();
    run("Duplicate...", "title=toProcess");
    setBackgroundColor(0, 0, 0);
    run("Subtract Background...", "rolling=50");
    saveAs("Tiff", out + "1-background.tif"); rename("toProcess");
    run("Gaussian Blur...", "sigma=2");
    saveAs("Tiff", out + "2-blur.tif"); rename("toProcess");
    setOption("ScaleConversions", true);
    run("8-bit");
    saveAs("Tiff", out + "3-8bit.tif"); rename("toProcess");
    run("Auto Local Threshold", "method=Phansalkar radius=25 parameter_1=0 parameter_2=0 white");
    saveAs("Tiff", out + "4-phansalkar.tif"); rename("toProcess");
    run("Gaussian Blur...", "sigma=2");
    saveAs("Tiff", out + "5-blur.tif"); rename("toProcess");
    run("Convert to Mask");
    saveAs("Tiff", out + "6-mask.tif"); rename("toProcess");
    run("Analyze Particles...", "size=0-10 add");
    if (roiManager("count") > 0) {
        roiManager("Fill");
        roiManager("reset");
    }
    saveAs("Tiff", out + "7-filled.tif"); rename("toProcess");
    run("Create Selection");
    selectWindow(originalTitle);
    run("Restore Selection");
    run("Clear Outside");
    run("Select None");
    saveAs("Tiff", out + "8-final.tif");
    close("*");
}
setBatchMode(false);
print("done " + done);
eval("script", "System.exit(0);");
