origin = getDirectory("Images to process");
tifDestination = getDirectory("Image destination (.tif)");
lista = getFileList(origin);
setBatchMode(true);

for (j=0; j<lista.length; j++) {
    showProgress(j+1, lista.length);
    
    roiManager("reset");
    
    open(origin + lista[j]);
    originalTitle = getTitle();
    
    run("Duplicate...", "title=toProcess");
    
    setBackgroundColor(0, 0, 0);
    run("Subtract Background...", "rolling=50");
    run("Gaussian Blur...", "sigma=2");
    setOption("ScaleConversions", true);
    run("8-bit");
    
    run("Auto Local Threshold", "method=Phansalkar radius=25 parameter_1=0 parameter_2=0 white");
    run("Gaussian Blur...", "sigma=2");
    run("Convert to Mask");
    
    run("Analyze Particles...", "size=0-10 add");
    if (roiManager("count") > 0) {
        roiManager("Fill");
        roiManager("reset");
    }
    
    run("Create Selection");
    
    selectWindow(originalTitle);
    run("Restore Selection");
    
    
    run("Clear Outside");         
    run("Select None");
    
    saveAs("Tiff", tifDestination + originalTitle + " - Processed method 2.5.tif");
    
    close("*");
}

setBatchMode(false);
print("Done :)");